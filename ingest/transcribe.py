import os
import time
import threading
import multiprocessing as mp

from ingest.resources import can_add_worker, estimate_max_workers, gpu_has_room

SCALE_CHECK_INTERVAL = 30  # seconds between scale-up checks

# Use 'spawn' to avoid CUDA re-init errors in forked subprocesses
_ctx = mp.get_context("spawn")


def _worker(input_q, result_q, model_name, worker_id, device):
    """Worker process: loads Whisper model on assigned device, consumes jobs."""
    import whisper
    model = whisper.load_model(model_name, device=device)
    result_q.put(("ready", worker_id, device))

    while True:
        item = input_q.get()
        if item is None:  # poison pill
            break

        safe_title, audio_path = item
        result_q.put(("working", worker_id, safe_title))
        try:
            result = model.transcribe(audio_path, language=None)
            result_q.put(("ok", safe_title, result["text"]))
        except Exception as e:
            result_q.put(("error", safe_title, str(e)))


class AutoScaleTranscriber:
    """Transcription pool that auto-scales workers based on system resources.

    First worker gets GPU (if it fits), all others get CPU.
    Periodically checks if the system has enough free RAM/CPU to add more workers.
    """

    def __init__(self, model_name, output_dir, status_file=None, max_workers=None):
        self.model_name = model_name
        self.output_dir = output_dir
        self.status_file = status_file
        self.input_q = _ctx.Queue()
        self.result_q = _ctx.Queue()
        self._workers = []
        self._gpu_assigned = False
        self._lock = threading.Lock()
        self._stop_monitor = threading.Event()

        if max_workers:
            self.max_workers = max_workers
        else:
            self.max_workers, _ = estimate_max_workers(model_name)

    def _next_device(self):
        """Assign GPU to the first worker if it fits, CPU for all others."""
        if not self._gpu_assigned and gpu_has_room(self.model_name):
            self._gpu_assigned = True
            return "cuda"
        return "cpu"

    def _spawn_worker(self):
        wid = len(self._workers)
        device = self._next_device()
        p = _ctx.Process(
            target=_worker,
            args=(self.input_q, self.result_q, self.model_name, wid, device),
        )
        p.start()
        self._workers.append(p)
        return wid

    def _alive_count(self):
        return sum(1 for w in self._workers if w.is_alive())

    def _monitor_loop(self, total_remaining):
        """Background thread that tries to scale up workers."""
        while not self._stop_monitor.is_set():
            self._stop_monitor.wait(SCALE_CHECK_INTERVAL)
            if self._stop_monitor.is_set():
                break

            with self._lock:
                alive = self._alive_count()
                if alive >= self.max_workers:
                    continue
                if self.input_q.empty():
                    continue

                ok, reason = can_add_worker(self.model_name, alive)
                if ok:
                    wid = self._spawn_worker()
                    self.result_q.put(("scale", f"worker-{wid}", reason))

    def run(self, files, on_event=None):
        """Run transcription with auto-scaling.

        Args:
            files: list of (safe_title, audio_path) tuples
            on_event: callback(event_type, safe_title, data) for progress

        Returns:
            (successes, failures)
        """
        if not files:
            return [], []

        os.makedirs(self.output_dir, exist_ok=True)

        # Feed queue
        for f in files:
            self.input_q.put(f)

        # Start with half of max or 1, whichever is larger
        initial = max(1, min(self.max_workers // 2, len(files)))
        for _ in range(initial):
            self._spawn_worker()

        # Wait for initial workers to load model
        ready_count = 0
        while ready_count < initial:
            msg = self.result_q.get()
            if msg[0] == "ready":
                ready_count += 1
                if on_event:
                    on_event("ready", f"worker-{msg[1]}", msg[2])

        # Start monitor thread for scaling
        monitor = threading.Thread(target=self._monitor_loop, args=(len(files),), daemon=True)
        monitor.start()

        # Collect results
        successes = []
        failures = []
        completed = 0
        total = len(files)

        while completed < total:
            status, safe_title, data = self.result_q.get()

            if status == "ok":
                txt_path = os.path.join(self.output_dir, f"{safe_title}.txt")
                with open(txt_path, "w") as f:
                    f.write(data)
                successes.append(safe_title)
                completed += 1
                self._update_status(safe_title, ok=True)
                if on_event:
                    on_event("ok", safe_title, f"{completed}/{total}")

            elif status == "error":
                failures.append((safe_title, data))
                completed += 1
                self._update_status(safe_title, ok=False, reason=data)
                if on_event:
                    on_event("error", safe_title, data)

            elif status == "working":
                if on_event:
                    on_event("working", safe_title, data)

            elif status == "scale":
                if on_event:
                    on_event("scale", safe_title, data)

            elif status == "ready":
                if on_event:
                    on_event("ready", safe_title, data)

        # Shutdown
        self._stop_monitor.set()
        for _ in self._workers:
            self.input_q.put(None)
        for w in self._workers:
            w.join(timeout=30)

        return successes, failures

    def _update_status(self, safe_title, ok=True, reason=""):
        """Update status.json immediately after each file."""
        if not self.status_file:
            return
        from storage.status import Status
        st = Status(self.status_file)
        if ok:
            st.mark_transcribed(safe_title)
        else:
            st.mark_failed(safe_title, reason=reason)


def transcribe_auto(files, output_dir, model_name="base", status_file=None, max_workers=None, on_event=None):
    """Convenience wrapper for AutoScaleTranscriber."""
    pool = AutoScaleTranscriber(model_name, output_dir, status_file, max_workers)
    return pool.run(files, on_event)
