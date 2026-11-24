"""P90: deterministic playback of embedded WAV through a real temporary file.
No Windows system-sound fallback. Failures are written to a user-accessible log.
"""
import logging
import os
import sys
import tempfile
import threading
import wave
import io
import queue
import ctypes
from pathlib import Path

_lock = threading.Lock()
_jobs = queue.Queue()
_worker_lock = threading.Lock()
_worker_started = False

def diagnose_windows_audio():
    """Diagnostic only: a working device and API cannot prove audible output."""
    if sys.platform != 'win32':
        return {'platform': sys.platform, 'device_count': None, 'note': 'Requires Windows 11 for real output test'}
    try:
        count = ctypes.windll.winmm.waveOutGetNumDevs()
        return {'platform': 'win32', 'device_count': int(count), 'note': 'Check Windows volume mixer and selected output device if silent'}
    except Exception as exc:
        return {'platform': 'win32', 'device_count': None, 'error': str(exc)}

def _ensure_worker():
    global _worker_started
    with _worker_lock:
        if not _worker_started:
            threading.Thread(target=_run_queue, daemon=True, name='P91-Audio-Queue').start()
            _worker_started = True

def _run_queue():
    while True:
        wav_data, label, on_result = _jobs.get()
        try:
            _play_once(wav_data, label, on_result)
        finally:
            _jobs.task_done()


def _log_path():
    folder = Path(os.environ.get('LOCALAPPDATA') or tempfile.gettempdir()) / 'AI_Font_Finder_PRO'
    folder.mkdir(parents=True, exist_ok=True)
    return folder / 'audio_errors.log'

def _play_once(wav_data, label, on_result=None):
    path = None
    try:
        if sys.platform != 'win32':
            raise RuntimeError('Audio playback requires Windows')
        with wave.open(io.BytesIO(wav_data), 'rb') as wf:
            if wf.getcomptype() != 'NONE' or wf.getnframes() == 0 or wf.getsampwidth() != 2:
                raise ValueError('Unsupported or empty WAV')
        import winsound
        fd, path = tempfile.mkstemp(prefix='ai_font_audio_', suffix='.wav')
        with os.fdopen(fd, 'wb') as out:
            out.write(wav_data)
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_NODEFAULT)
        if on_result:
            on_result(True, label + ': Windows playback API succeeded; audible volume is not independently verified')
    except Exception as exc:
        try:
            logger = logging.getLogger('AI_Font_Finder_PRO.audio')
            logger.setLevel(logging.ERROR)
            log_file = str(_log_path())
            if not any(isinstance(h, logging.FileHandler) and h.baseFilename == log_file for h in logger.handlers):
                logger.addHandler(logging.FileHandler(log_file, encoding='utf-8'))
            logger.exception('Playback failed: %s; diagnostics=%s', label, diagnose_windows_audio())
        except Exception:
            log_file = '(could not write audio log)'
        if on_result:
            on_result(False, '%s: %s | %s' % (label, exc, log_file))
    finally:
        if path:
            try: os.remove(path)
            except OSError: pass

def play_wav(wav_data, label, on_result=None):
    """Serialize notifications, preventing overlapping sound on parallel events."""
    _ensure_worker()
    _jobs.put((wav_data, label, on_result))
    return True
