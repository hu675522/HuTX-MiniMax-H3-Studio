"""Offline output inspection; audio equality evidence is not a lip-sync verdict."""
import json
from pathlib import Path
import wave
import av
import numpy as np
from PIL import Image,ImageDraw

root=Path(__file__).resolve().parents[1]/'.local-smoke-v040'
with wave.open(str(root/'input/speech.wav')) as source:
    rate=source.getframerate();channels=source.getnchannels()
    original=np.frombuffer(source.readframes(source.getnframes()),dtype='<i2').reshape(-1,channels).mean(axis=1)/32768
records=[]
for path in sorted((root/'output/speech_acceptance').glob('*.mp4')):
    with av.open(str(path)) as container:
        stream=container.streams.video[0];fps=float(stream.average_rate)
        frames=list(container.decode(video=0))
    with av.open(str(path)) as container:
        resampler=av.AudioResampler(format='fltp',layout='mono',rate=rate)
        chunks=[]
        for frame in container.decode(audio=0):
            chunks.extend(f.to_ndarray().reshape(-1) for f in resampler.resample(frame))
        chunks.extend(f.to_ndarray().reshape(-1) for f in resampler.resample(None))
        decoded=np.concatenate(chunks)
    count=len(original)
    correlation=float(np.corrcoef(original,decoded[:count])[0,1]) if len(decoded)>=count else 0
    record={'file':str(path),'frames':len(frames),'fps':fps,'video_seconds':len(frames)/fps,
        'source_seconds':count/rate,'decoded_audio_seconds':len(decoded)/rate,
        'source_prefix_correlation':correlation,'source_not_truncated':len(decoded)>=count,
        'lip_sync_acceptance':'requires human audiovisual review'}
    if len(decoded)<count or correlation<.98:raise RuntimeError('Output audio differs from adopted speech')
    tiles=[]
    for second in (.5,1.5,2.5,3.5,4.5,5.3):
        image=frames[min(round(second*fps),len(frames)-1)].to_image()
        image.thumbnail((320,320));tile=Image.new('RGB',(320,345),'#10202a');tile.paste(image,((320-image.width)//2,20))
        ImageDraw.Draw(tile).text((8,325),f'{second:.1f}s',fill='white');tiles.append(tile)
    sheet=Image.new('RGB',(960,690),'#10202a')
    for index,tile in enumerate(tiles):sheet.paste(tile,((index%3)*320,(index//3)*345))
    sheet.save(root/(path.stem+'-contact.png'))
    records.append(record)
(root/'speech-media-verification.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(records,ensure_ascii=True))
