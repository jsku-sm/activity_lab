"""Bounded uploads and PDF rasterization. No active HTML/SVG is accepted."""
import io
from PIL import Image, ImageDraw
from .core import ActivityError
MAX_BYTES=8*1024*1024

def normalize_upload(raw,mime,name):
    if not isinstance(raw,bytes) or not raw or len(raw)>MAX_BYTES:
        raise ActivityError('파일은 8MB 이하로 올려 주세요.')
    name=str(name).replace('/','_').replace('\\','_')[:100]
    if mime.startswith('image/'):
        try:
            image=Image.open(io.BytesIO(raw))
            if image.width*image.height>24000000: raise ActivityError('이미지가 너무 커요.')
            image.load(); image=image.convert('RGB'); image.thumbnail((1800,2400))
            out=io.BytesIO(); image.save(out,format='JPEG',quality=85)
            return out.getvalue(),'image/jpeg',name.rsplit('.',1)[0]+'.jpg'
        except ActivityError: raise
        except Exception: raise ActivityError('지원하는 이미지 파일인지 확인해 주세요.')
    audio={
        'audio/wav':raw[:4]==b'RIFF', 'audio/x-wav':raw[:4]==b'RIFF',
        'audio/mpeg':raw[:3]==b'ID3' or raw[:1]==b'\xff',
        'audio/mp3':raw[:3]==b'ID3' or raw[:1]==b'\xff',
        'audio/webm':raw[:4]==b'\x1aE\xdf\xa3', 'audio/ogg':raw[:4]==b'OggS',
        'audio/mp4':raw[4:8]==b'ftyp', 'audio/x-m4a':raw[4:8]==b'ftyp',
    }
    mime=mime.split(';')[0]
    if mime in audio and audio[mime]: return raw,mime,name
    raise ActivityError('PNG/JPG 이미지 또는 WAV/MP3/WebM/M4A 음성 파일을 올려 주세요.')

def pdf_pages(raw):
    if len(raw)>MAX_BYTES: raise ActivityError('PDF는 8MB 이하로 올려 주세요.')
    import fitz
    try:
        with fitz.open(stream=raw,filetype='pdf') as doc:
            if doc.needs_pass: raise ActivityError('암호가 없는 PDF를 올려 주세요.')
            if not 1<=len(doc)<=20: raise ActivityError('PDF는 1~20쪽까지 한 번에 추가할 수 있어요.')
            pages=[]
            for page in doc:
                scale=min(1.5,1600/max(page.rect.width,page.rect.height))
                pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False)
                pages.append(pix.tobytes('png'))
            return pages
    except ActivityError: raise
    except Exception: raise ActivityError('PDF를 읽지 못했어요. 파일을 확인해 주세요.')

def render_strokes(response,background=None):
    if background:
        image=Image.open(io.BytesIO(background)).convert('RGB')
        image.thumbnail((1400,1800))
    else:
        image=Image.new('RGB',(1000,700),'white')
    width,height=image.size
    draw=ImageDraw.Draw(image)
    for stroke in response.get('strokes',[]):
        points=stroke.get('points',[])
        if not points: continue
        pts=[(float(p[0])*width,float(p[1])*height) for p in points[:5000]]
        if len(pts)==1: pts.append((pts[0][0]+.3,pts[0][1]+.3))
        color=stroke.get('color','#233659')
        pen_width=max(1,min(16,int(float(stroke.get('width',3))*width/1000)))
        try: draw.line(pts,fill=color,width=pen_width)
        except (ValueError,TypeError): draw.line(pts,fill='#233659',width=pen_width)
    buf=io.BytesIO(); image.save(buf,format='PNG'); return buf.getvalue()
