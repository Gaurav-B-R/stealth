#!/usr/bin/env python3
"""Render a branded, editable Rilono product demo from real product captures.

Usage: python render_demo.py manifest.json [--scene ID] [--preview-only]
All paths in the manifest are relative to this directory. No product data is
created or altered. Screenshot pixels are only cropped, scaled and animated.
"""
from __future__ import annotations
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import wave
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parent
FFMPEG = os.environ.get('FFMPEG', '/private/tmp/rilono-video-tools/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1')
W, H, FPS, SR = 1920, 1080, 30, 48000
SCREEN = (120, 156, 1680, 856)
INK = '#171a34'
MUTED = '#575e7b'
BRAND = '#6366f1'
FONT = '/Applications/Camo Studio.app/Contents/Resources/Inter.ttf'
FONT_FALLBACK = '/System/Library/Fonts/Supplemental/Arial.ttf'
FONT_BOLD = '/System/Library/Fonts/Supplemental/Arial Bold.ttf'


def run(args):
    subprocess.run([str(x) for x in args], check=True)


def font(size, bold=False):
    path = FONT if Path(FONT).exists() else (FONT_BOLD if bold else FONT_FALLBACK)
    f = ImageFont.truetype(path, size)
    if path == FONT:
        try:
            f.set_variation_by_axes([700 if bold else 450])
        except (OSError, AttributeError):
            pass
    return f


def wrap(draw, text, f, max_width):
    lines = []
    for paragraph in text.split('\n'):
        line = ''
        for word in paragraph.split():
            proposed = f'{line} {word}'.strip()
            if line and draw.textlength(proposed, font=f) > max_width:
                lines.append(line)
                line = word
            else:
                line = proposed
        lines.append(line)
    return lines


def label(draw, xy, text, size, fill=INK, bold=False, max_width=None, line_height=1.2):
    f = font(size, bold)
    lines = wrap(draw, text, f, max_width) if max_width else text.split('\n')
    for i, line in enumerate(lines):
        draw.text((xy[0], xy[1] + int(i * size * line_height)), line, font=f, fill=fill)
    return len(lines) * size * line_height


def gradient_background(dark=False):
    yy, xx = np.mgrid[0:H, 0:W]
    glow = np.exp(-(((xx-W*.86)/(W*.65))**2 + ((yy-H*.14)/(H*.75))**2))
    glow2 = np.exp(-(((xx-W*.13)/(W*.6))**2 + ((yy-H*.93)/(H*.85))**2))
    if dark:
        base = np.array([19., 24., 53.])
        color = base + glow[:,:,None]*np.array([24,17,57]) + glow2[:,:,None]*np.array([8,12,25])
    else:
        base = np.array([250., 250., 255.])
        color = base - glow[:,:,None]*np.array([18,20,1]) - glow2[:,:,None]*np.array([9,6,0])
    return Image.fromarray(np.uint8(np.clip(color,0,255)), 'RGB')


def fit_image(path, size, crop=None):
    image = Image.open(path).convert('RGB')
    if crop:
        image = image.crop(tuple(crop))
    original_size = image.size
    ratio = min(size[0]/image.width, size[1]/image.height)
    resized = image.resize((round(image.width*ratio), round(image.height*ratio)), Image.Resampling.LANCZOS)
    canvas = Image.new('RGB', size, '#ffffff')
    offset = ((size[0]-resized.width)//2, (size[1]-resized.height)//2)
    canvas.paste(resized, offset)
    return canvas, original_size, ratio, offset


def base_scene(scene, index, total):
    bg = gradient_background()
    draw = ImageDraw.Draw(bg)
    chapter = scene.get('chapter', f'{index:02} / RILONO ENTERPRISE')
    label(draw, (122, 26), chapter.upper(), 19, BRAND, True)
    headline = scene.get('headline', '')
    size = 48
    while draw.textlength(headline, font=font(size,True)) > 1500 and size > 34:
        size -= 1
    label(draw, (118, 60), headline, size, bold=True)
    draw.rounded_rectangle((1698, 38, 1800, 91), radius=26, fill='#ffffff')
    label(draw, (1722, 51), f'{index:02}/{total:02}', 21, MUTED, True)
    # Soft frame shadow, drawn entirely outside product pixels.
    shadow = Image.new('RGBA', (W,H), (0,0,0,0))
    sd = ImageDraw.Draw(shadow)
    x,y,w,h = SCREEN
    sd.rounded_rectangle((x-8,y-4,x+w+8,y+h+14),radius=18,fill=(30,35,78,42))
    shadow = shadow.filter(ImageFilter.GaussianBlur(20))
    bg = Image.alpha_composite(bg.convert('RGBA'),shadow).convert('RGB')
    draw = ImageDraw.Draw(bg)
    draw.rounded_rectangle((x-7,y-7,x+w+7,y+h+7),radius=15,fill='white')
    desc = scene.get('description','')
    fsize = 24
    while draw.textlength(desc,font=font(fsize)) > 1550 and fsize > 17:
        fsize -= 1
    draw.ellipse((122,1037,130,1045), fill=BRAND)
    label(draw,(145,1029),desc,fsize,MUTED)
    return bg


def title_scene(scene, kind):
    dark = kind == 'outro'
    bg = gradient_background(dark)
    draw = ImageDraw.Draw(bg)
    # Existing logo is used as supplied, on a white badge.
    logo_source = ROOT.parent.parent / 'static' / 'logo.png'
    if not logo_source.exists():
        logo_source = ROOT.parent.parent.parent / 'static' / 'logo.png'
    if logo_source.exists():
        logo_copy = ROOT/'assets'/'rilono-logo.png'
        if not logo_copy.exists():
            shutil.copyfile(logo_source,logo_copy)
        logo = Image.open(logo_copy).convert('RGB').resize((92,92),Image.Resampling.LANCZOS)
        bg.paste(logo,(120,92))
    draw = ImageDraw.Draw(bg)
    color = '#ffffff' if dark else INK
    secondary = '#c9cbea' if dark else MUTED
    label(draw,(239,103),'Rilono',42,color,True)
    label(draw,(242,151),'ENTERPRISE',17,'#b0b2ff' if dark else BRAND,True)
    label(draw,(124,286),scene.get('eyebrow','BUILT FOR STUDY-ABROAD CONSULTANCIES'),21,'#b0b2ff' if dark else BRAND,True)
    title = scene.get('headline','Your consultancy.\nConnected.')
    height = label(draw,(116,339),title,96,color,True,max_width=1650,line_height=1.08)
    description = scene.get('description','Clients, applications and your team. One clear workspace.')
    label(draw,(124,379+height),description,32,secondary,max_width=1380,line_height=1.35)
    cta = scene.get('cta','Product walkthrough' if kind=='intro' else 'Explore Rilono Enterprise  •  rilono.com/enterprise')
    draw.rounded_rectangle((120,877,1800,969),radius=20,fill='#6366f1' if dark else '#ffffff')
    label(draw,(154,902),cta,29,'#ffffff' if dark else BRAND,True)
    draw.line((120,1030,1800,1030), fill='#55577d' if dark else '#dfe0f0', width=2)
    label(draw,(124,1044),'RILONO ENTERPRISE',15,'#a7accb' if dark else '#8288a7',True)
    return bg


def create_scene_assets(scene,index,total):
    assets=ROOT/'assets'/'render';assets.mkdir(parents=True,exist_ok=True)
    ident=scene['id']
    kind=scene.get('type','screen')
    bg=title_scene(scene,kind) if kind in ('intro','outro') else base_scene(scene,index,total)
    bgpath=assets/f'{ident}-base.png';bg.save(bgpath)
    shotpath=assets/f'{ident}-screen.png'
    highlightpath=assets/f'{ident}-highlight.png'
    preview=bg.copy()
    if kind=='screen':
        path=ROOT/scene['image']
        shot,orig,ratio,offset=fit_image(path,SCREEN[2:],scene.get('crop'))
        shot.save(shotpath)
        preview.paste(shot,SCREEN[:2])
        highlight=Image.new('RGBA',(W,H),(0,0,0,0))
        focus=scene.get('focus')
        if focus:
            fx,fy,fw,fh=focus
            x=SCREEN[0]+offset[0]+round(fx*orig[0]*ratio)
            y=SCREEN[1]+offset[1]+round(fy*orig[1]*ratio)
            fw=round(fw*orig[0]*ratio);fh=round(fh*orig[1]*ratio)
            hd=ImageDraw.Draw(highlight)
            hd.rounded_rectangle((x-5,y-5,x+fw+5,y+fh+5),radius=12,outline=(99,102,241,240),width=4)
            hd.rounded_rectangle((x-10,y-10,x+fw+10,y+fh+10),radius=17,outline=(99,102,241,55),width=6)
            preview=Image.alpha_composite(preview.convert('RGBA'),highlight).convert('RGB')
        highlight.save(highlightpath)
    previewpath=assets/f'{ident}-preview.jpg';preview.save(previewpath,quality=94)
    return bgpath,shotpath,highlightpath,previewpath


def render_scene(scene,index,total,force=False,preview_only=False):
    paths=create_scene_assets(scene,index,total)
    if preview_only:
        return paths[3]
    output=ROOT/'scenes'/f"{scene['id']}.mp4";output.parent.mkdir(exist_ok=True)
    duration=float(scene['duration']);frames=round(duration*FPS)
    if output.exists() and not force:
        return output
    kind=scene.get('type','screen')
    args=[FFMPEG,'-hide_banner','-loglevel','error','-y','-loop','1','-framerate',str(FPS),'-i',paths[0]]
    fade_color='0x171a34' if kind=='outro' else '0xf5f5fc'
    fade=f"fade=t=in:st=0:d=0.22:color={fade_color},fade=t=out:st={duration-0.22:.3f}:d=0.22:color={fade_color}"
    if kind=='screen':
        args+=['-loop','1','-framerate',str(FPS),'-i',paths[1],'-loop','1','-framerate',str(FPS),'-i',paths[2]]
        zoom=float(scene.get('zoom',0.022))
        pan=scene.get('pan',[0.5,0.5])
        # Upscale first so subpixel camera movement remains smooth at output resolution.
        filt=(f"[1:v]scale=3360:1712,zoompan=z='1+{zoom}*on/{max(frames-1,1)}':"
              f"x='(iw-iw/zoom)*{pan[0]}':y='(ih-ih/zoom)*{pan[1]}':d={frames}:s={SCREEN[2]}x{SCREEN[3]}:fps={FPS}[shot];"
              f"[0:v][shot]overlay={SCREEN[0]}:{SCREEN[1]}:shortest=1[base];"
              f"[2:v]format=rgba,fade=t=in:st=1.2:d=0.45:alpha=1,fade=t=out:st={max(duration-1.5,2):.3f}:d=0.45:alpha=1[hi];"
              f"[base][hi]overlay=0:0:shortest=1,{fade},format=yuv420p[v]")
    else:
        # Subtle editorial push on the title/end card.
        filt=(f"[0:v]scale=2880:1620,zoompan=z='1+0.012*on/{max(frames-1,1)}':"
              f"x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d={frames}:s={W}x{H}:fps={FPS},"
              f"{fade},format=yuv420p[v]")
    args+=['-filter_complex',filt,'-map','[v]','-frames:v',str(frames),'-an','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',output]
    print(f"Rendering {scene['id']} ({duration:.1f}s)",flush=True)
    run(args)
    return output


def read_wav(path):
    with wave.open(str(path),'rb') as wav:
        rate=wav.getframerate();channels=wav.getnchannels();width=wav.getsampwidth()
        if rate!=SR or width!=2:
            raise ValueError(f'{path}: narration must be 48kHz PCM16 WAV')
        a=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').astype(np.float32)/32768
        return a.reshape(-1,channels).mean(axis=1)


def write_wav(path,a):
    if a.ndim==1: a=a[:,None]
    with wave.open(str(path),'wb') as wav:
        wav.setnchannels(a.shape[1]);wav.setsampwidth(2);wav.setframerate(SR)
        wav.writeframes((np.clip(a,-1,1)*32767).astype('<i2').tobytes())


def make_audio(manifest):
    scenes=manifest['scenes'];duration=sum(float(s['duration']) for s in scenes)
    n=round(duration*SR);voice=np.zeros(n,dtype=np.float32);cursor=0
    captions=[]
    for scene in scenes:
        count=round(float(scene['duration'])*SR)
        if scene.get('narration_audio'):
            a=read_wav(ROOT/scene['narration_audio'])
            offset=round(float(scene.get('narration_delay',0.4))*SR)
            if len(a)+offset>count:
                raise ValueError(f"Narration for {scene['id']} runs {(len(a)+offset-count)/SR:.2f}s past scene end")
            # Normalize voice peaks conservatively, preserving dynamics.
            peak=max(float(np.max(np.abs(a))),0.01)
            a=a*min(0.75/peak,3.0)
            voice[cursor+offset:cursor+offset+len(a)]=a
        if scene.get('narration'):
            captions.append((cursor/SR,(cursor+count)/SR,scene['narration']))
        cursor+=count
    voicepath=ROOT/'assets'/'narration-full.wav';write_wav(voicepath,voice)
    # Original understated synth bed: warm sustained chords, soft bell-like pulses.
    # Everything is generated mathematically; no third-party licensed recording.
    t=np.arange(n,dtype=np.float64)/SR
    music=np.zeros((n,2),dtype=np.float32)
    bpm=92;beat=60/bpm;bar=beat*8
    chords=[[146.832,184.997,220.0],[130.813,164.814,195.998],[110.,138.591,164.814],[130.813,164.814,195.998]]
    for barstart in np.arange(0,duration,bar):
        b=int(barstart/bar)%len(chords);end=min(barstart+bar+1.0,duration)
        i0=round(barstart*SR);i1=round(end*SR);local=t[i0:i1]-barstart
        envelope=np.minimum(local/1.2,1)*np.minimum((end-barstart-local)/1.2,1)
        envelope=np.maximum(envelope,0)
        for k,freq in enumerate(chords[b]):
            tone=(np.sin(2*np.pi*freq*local)+0.18*np.sin(2*np.pi*freq*2*local))/len(chords[b])
            music[i0:i1,0]+=tone*envelope*.075*(.9+.1*k)
            music[i0:i1,1]+=np.sin(2*np.pi*(freq*1.0007)*local)*envelope*.075/len(chords[b])
        for j in range(8):
            pos=barstart+j*beat
            if pos>=duration:break
            p0=round(pos*SR);p1=min(n,p0+round(beat*1.4*SR));lt=t[p0:p1]-pos
            f=chords[b][j%3]*4
            env=(1-np.exp(-lt*35))*np.exp(-lt*5)
            pluck=(np.sin(2*np.pi*f*lt)+.12*np.sin(2*np.pi*f*2*lt))*env*.014
            music[p0:p1,0]+=pluck*(.7 if j%2 else 1)
            music[p0:p1,1]+=pluck*(1 if j%2 else .7)
    fade=np.minimum(t/2,1)*np.minimum((duration-t)/2.5,1)
    music*=np.maximum(fade,0)[:,None]
    # Gentle further duck under spoken sections, no pumping envelope.
    active=np.abs(voice)>0.001
    if active.any():
        block=4800
        for i in range(0,n,block):
            if np.any(active[i:min(i+block,n)]):music[i:min(i+block,n)]*=.6
    musicpath=ROOT/'assets'/'original-music-bed.wav';write_wav(musicpath,music)
    finalaudio=ROOT/'assets'/'mixed-audio.wav';write_wav(finalaudio,voice[:,None]+music)
    def tc(s):
        ms=round(s*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);ss,ms=divmod(ms,1000)
        return f'{h:02}:{m:02}:{ss:02},{ms:03}'
    srt='\n\n'.join(f'{i+1}\n{tc(a)} --> {tc(b)}\n{text}' for i,(a,b,text) in enumerate(captions))
    (ROOT/'exports'/'Rilono-Enterprise-Demo.srt').write_text(srt+'\n')
    return voicepath,musicpath,finalaudio


def make_xml(manifest,scene_paths,voicepath,musicpath):
    def e(parent,name,value=None,**attrs):
        elem=ET.SubElement(parent,name,attrs)
        if value is not None:elem.text=str(value)
        return elem
    def rate(parent):
        r=e(parent,'rate');e(r,'timebase',FPS);e(r,'ntsc','FALSE')
    def videoformat(parent):
        sample=e(parent,'samplecharacteristics');rate(sample)
        e(sample,'width',W);e(sample,'height',H);e(sample,'anamorphic','FALSE');e(sample,'pixelaspectratio','square');e(sample,'fielddominance','none')
    def file(parent,ident,path,frames,audio=False,channels=1):
        f=e(parent,'file',id=ident);e(f,'name',path.name);e(f,'pathurl',path.resolve().as_uri());rate(f);e(f,'duration',frames)
        media=e(f,'media')
        if audio:
            a=e(media,'audio');s=e(a,'samplecharacteristics');e(s,'depth',16);e(s,'samplerate',SR);e(a,'channelcount',channels)
        else:
            video=e(media,'video');videoformat(video)
        return f
    frames=sum(round(float(s['duration'])*FPS) for s in manifest['scenes'])
    root=ET.Element('xmeml',version='5');seq=e(root,'sequence',id='rilono-demo-sequence')
    e(seq,'name',manifest.get('title','Rilono Enterprise — Product Demo'));e(seq,'duration',frames);rate(seq)
    tc=e(seq,'timecode');rate(tc);e(tc,'string','00:00:00:00');e(tc,'frame',0);e(tc,'displayformat','NDF')
    media=e(seq,'media');video=e(media,'video');videoformat(e(video,'format'));track=e(video,'track')
    cursor=0
    for i,(scene,path) in enumerate(zip(manifest['scenes'],scene_paths)):
        n=round(float(scene['duration'])*FPS);clip=e(track,'clipitem',id=f'video-{i+1}')
        e(clip,'name',scene.get('headline',scene['id']).replace('\n',' '));e(clip,'enabled','TRUE');e(clip,'duration',n);rate(clip)
        e(clip,'start',cursor);e(clip,'end',cursor+n);e(clip,'in',0);e(clip,'out',n)
        file(clip,f'video-file-{i+1}',path,n)
        e(clip,'compositemode','normal');cursor+=n
    e(track,'enabled','TRUE');e(track,'locked','FALSE')
    audio=e(media,'audio');e(audio,'numOutputChannels',2)
    af=e(audio,'format');sample=e(af,'samplecharacteristics');e(sample,'depth',16);e(sample,'samplerate',SR)
    for i,(path,channel,channels) in enumerate([(voicepath,1,1),(musicpath,1,2),(musicpath,2,2)]):
        tr=e(audio,'track');cl=e(tr,'clipitem',id=f'audio-{i+1}')
        e(cl,'name','Narration' if i==0 else 'Original ambient music');e(cl,'enabled','TRUE');e(cl,'duration',frames);rate(cl)
        e(cl,'start',0);e(cl,'end',frames);e(cl,'in',0);e(cl,'out',frames)
        file(cl,f'audio-file-{i+1}',path,frames,True,channels)
        source=e(cl,'sourcetrack');e(source,'mediatype','audio');e(source,'trackindex',channel)
        e(tr,'enabled','TRUE');e(tr,'locked','FALSE')
    output=ROOT/'project'/'Rilono-Enterprise-Demo.xml';output.parent.mkdir(exist_ok=True)
    ET.indent(root,space='  ')
    xml=ET.tostring(root,encoding='unicode')
    output.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n'+xml+'\n')
    return output


def main():
    parser=argparse.ArgumentParser();parser.add_argument('manifest');parser.add_argument('--scene');parser.add_argument('--preview-only',action='store_true');parser.add_argument('--force',action='store_true')
    args=parser.parse_args();mpath=Path(args.manifest)
    if not mpath.is_absolute():mpath=ROOT/mpath
    manifest=json.loads(mpath.read_text());scenes=manifest['scenes']
    for folder in ['assets','scenes','exports','project']:(ROOT/folder).mkdir(exist_ok=True)
    selected=[(i,s) for i,s in enumerate(scenes,1) if not args.scene or s['id']==args.scene]
    paths=[]
    for i,scene in selected:paths.append(render_scene(scene,i,len(scenes),args.force,args.preview_only))
    if args.preview_only or args.scene:
        print('\n'.join(str(p) for p in paths));return
    voice,music,audio=make_audio(manifest)
    listfile=ROOT/'assets'/'scene-concat.txt'
    listfile.write_text(''.join("file '"+str(p.resolve()).replace("'","'\\''")+"'\n" for p in paths))
    output=ROOT/'exports'/'Rilono-Enterprise-Demo.mp4'
    run([FFMPEG,'-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',listfile,'-i',audio,'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k','-ar',SR,'-movflags','+faststart','-shortest',output])
    xml=make_xml(manifest,paths,voice,music)
    print(f'FINAL_VIDEO={output}\nPREMIERE_XML={xml}')


if __name__=='__main__':main()
