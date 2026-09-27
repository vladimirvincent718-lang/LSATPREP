export function lyricLines(text) {
  return text.split('\n').flatMap(line=>{
    const times=[...line.matchAll(/\[(\d+):(\d+(?:\.\d+)?)\]/g)];
    const words=line.replace(/\[\d+:\d+(?:\.\d+)?\]/g,'').trim();
    return times.length ? times.map(t=>({time:Number(t[1])*60+Number(t[2]),text:words})) : [{time:null,text:words}];
  });
}

export default function({parentElement,data}) {
  let root=parentElement.querySelector('.karaoke-player');
  if(!root){
    root=document.createElement('section');root.className='karaoke-player';parentElement.append(root);
    root.style.cssText='padding:20px;border:1px solid #dddff0;border-radius:16px;background:#fafaff';
    const audio=document.createElement('audio');audio.controls=true;audio.style.width='100%';audio.src=data.src;root.append(audio);root.audio=audio;
    const lyrics=document.createElement('div');lyrics.style.cssText='max-height:320px;overflow:auto;margin-top:16px';root.append(lyrics);root.lyrics=lyrics;
    root.highlight=index=>{
      [...lyrics.children].forEach((line,i)=>{line.style.background=i===index?'#e1e3ff':'transparent';line.style.fontWeight=i===index?'700':'400';});
    };
    audio.ontimeupdate=()=>{
      let active=-1;root.lines.forEach((line,i)=>{if(line.time!==null && line.time<=audio.currentTime)active=i;});
      if(active>=0)root.highlight(active);
    };
  }
  root.lines=lyricLines(data.lyrics);
  root.lyrics.replaceChildren();
  root.lines.forEach((line,i)=>{
    const button=document.createElement('button');button.textContent=line.text||'·';
    button.style.cssText='display:block;width:100%;text-align:left;white-space:pre-wrap;font:inherit;font-size:20px;line-height:1.6;border:0;border-radius:8px;padding:8px 12px;color:#292746;cursor:pointer;background:transparent';
    button.onclick=()=>{if(line.time!==null)root.audio.currentTime=line.time;root.highlight(i);};
    root.lyrics.append(button);
  });
  return ()=>queueMicrotask(()=>{if(!root.isConnected)root.audio.pause();});
}
