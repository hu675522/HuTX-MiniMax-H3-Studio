"""Reference checks; Silero inference runs only inside the isolated worker."""
import array
import math
import sys
from .speech_errors import SpeechFailure


def check_reference_energy(pcm):
    pcm.validate()
    samples=array.array('h',pcm.data)
    if sys.byteorder!='little':samples.byteswap()
    # Cloud enrollment uses the first channel, so validate that same channel.
    values=samples[::pcm.channels]
    mean=sum(values)/len(values)
    rms=math.sqrt(sum((value-mean)**2 for value in values)/len(values))/32768
    if rms < 0.001:raise SpeechFailure('reference_silent')


def check_speech_onnx(audio,sample_rate,model):
    """Silero v6 fixed ONNX interface: 512 samples + 64 context at 16 kHz.

    Detection is a quality heuristic, not a guarantee of clean speech or identity.
    """
    import numpy as np
    import onnxruntime as ort
    import torch
    import torchaudio
    signal=np.asarray(audio,dtype=np.float32)
    if signal.ndim==2:signal=signal[:,0]
    if sample_rate!=16000:
        signal=torchaudio.functional.resample(torch.from_numpy(signal),sample_rate,16000).numpy()
    options=ort.SessionOptions();options.intra_op_num_threads=1;options.inter_op_num_threads=1
    session=ort.InferenceSession(str(model),sess_options=options,providers=['CPUExecutionProvider'])
    state=np.zeros((2,1,128),np.float32);context=np.zeros((1,64),np.float32)
    longest=consecutive=0
    for offset in range(0,len(signal),512):
        chunk=np.pad(signal[offset:offset+512],(0,max(0,512-len(signal[offset:offset+512]))))[None,:]
        window=np.concatenate((context,chunk),axis=1)
        score,state=session.run(None,{'input':window,'state':state,'sr':np.array(16000,dtype=np.int64)})
        context=chunk[:,-64:]
        consecutive=consecutive+1 if float(score.flat[0])>=0.5 else 0
        longest=max(longest,consecutive)
    if longest*512/16000 < 0.256:raise SpeechFailure('reference_speech')
    return round(longest*512/16000,3)
