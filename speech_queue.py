"""Coordinate preview with the host queue without changing video nodes.

The gate is held from queue dispatch through task_done. Preview holds the same
gate until its worker has exited. Queue put/status never wait on this gate.
"""
import threading
from contextlib import contextmanager
from .speech_errors import SpeechFailure


class QueueGate:
    def __init__(self,queue):
        self.queue=queue;self.gate=threading.Lock();self.jobs=set()
        original_get,original_done=queue.get,queue.task_done
        def get(*args,**kwargs):
            result=original_get(*args,**kwargs)
            if result is not None:
                self.gate.acquire()
                self.jobs.add(result[1])
            return result
        def done(item_id,*args,**kwargs):
            try:return original_done(item_id,*args,**kwargs)
            finally:
                if item_id in self.jobs:
                    self.jobs.remove(item_id);self.gate.release()
        queue.get=get;queue.task_done=done

    @contextmanager
    def preview(self):
        if not self.gate.acquire(blocking=False):raise SpeechFailure('queue_busy')
        try:
            if self.queue.get_tasks_remaining():raise SpeechFailure('queue_busy')
            yield
        finally:self.gate.release()


def install_queue_gate(instance):
    queue=getattr(instance,'prompt_queue',None)
    if queue is None or not all(callable(getattr(queue,n,None)) for n in ('get','task_done','get_tasks_remaining')):
        return None
    if not hasattr(queue,'_hutx_speech_gate'):
        queue._hutx_speech_gate=QueueGate(queue)
    return queue._hutx_speech_gate


@contextmanager
def local_preview_gate():
    from server import PromptServer
    gate=install_queue_gate(PromptServer.instance)
    if gate is None:raise SpeechFailure('queue_unsupported')
    with gate.preview():yield
