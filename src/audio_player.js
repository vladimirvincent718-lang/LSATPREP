// Community Cloud serves the app behind /~/+; root media URLs hit its HTML shell.
export function resolveAudioSource(src, pathname) {
  return src.startsWith('/media/') && pathname.startsWith('/~/+/') ? '/~/+' + src : src;
}

// Timestamped passages are exact; individual words are interpolated within them.
export function transcriptTimeline(text, duration) {
  if (!text?.trim() || !Number.isFinite(duration) || duration <= 0) return {words:[], timed:false};
  const clock=value=>value.replace(',', '.').split(':').reduce((n,v)=>n*60+Number(v),0);
  const stamp='(?:\\d+:)?\\d{1,2}:\\d{2}(?:[.,]\\d+)?';
  const range=new RegExp(`^(${stamp})\\s*-->\\s*(${stamp})`);
  const point=new RegExp(`^\\[?(${stamp})\\]?\\s+(.+)$`);
  const cues=[];let current=null;
  for(const raw of text.split(/\r?\n/)) {
    const line=raw.trim();let match=line.match(range);
    if(match){current={start:clock(match[1]),end:clock(match[2]),text:''};cues.push(current);continue;}
    match=line.match(point);
    if(match){current={start:clock(match[1]),text:match[2]};cues.push(current);continue;}
    if(!line){current=null;continue;}
    if(current)current.text+=(current.text?' ':'')+line;
  }
  const timed=cues.length>0;
  if(!timed)cues.push({start:0,end:duration,text});
  const words=[];
  cues.forEach((cue,i)=>{
    const start=Math.max(0,cue.start),end=Math.min(duration,cue.end??cues[i+1]?.start??duration);
    if(end<=start)return;
    const tokens=cue.text.trim().split(/\s+/).filter(Boolean);
    tokens.forEach((text,j)=>words.push({text,start:start+(end-start)*j/tokens.length,end:start+(end-start)*(j+1)/tokens.length,cue:i}));
  });
  words.sort((a,b)=>a.start-b.start);
  return {words,timed};
}

const progressModes=['Elapsed time','Time remaining','Percent completed','Percent remaining'];
export function progressDisplay(position,duration,mode=0) {
  if(!Number.isFinite(duration)||duration<=0)return 'Loading…';
  const current=Math.max(0,Math.min(duration,Number.isFinite(position)?position:0));
  const clock=seconds=>`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;
  if(mode===0)return `${clock(Math.floor(current))} / ${clock(Math.floor(duration))}`;
  if(mode===1)return `${clock(Math.ceil(duration-current))} remaining`;
  const percent=100*(mode===3?duration-current:current)/duration;
  return `${percent.toFixed(1)}% ${mode===3?'remaining':'completed'}`;
}

export default function({parentElement, data, setStateValue}) {
  let root = parentElement.querySelector('.audio-study');
  if (!root) {
    root = document.createElement('section'); root.className = 'audio-study';
    parentElement.append(root);
    root.innerHTML = `<style>
      .audio-study audio::-webkit-media-controls-current-time-display,
      .audio-study audio::-webkit-media-controls-time-remaining-display {display:none;}
      .audio-study .completion-bar {display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:12px;}
      .audio-study .completion-badge {padding:6px 10px;border-radius:20px;background:#f1f5f9;font-weight:700;}
      .audio-study .completion-badge.is-complete {background:#dcfce7;color:#166534;}
      .audio-study .transport {display:flex;align-items:center;gap:12px;flex-wrap:wrap;background:#f1f3f4;border-radius:18px;padding:8px;}
      .audio-study .transport audio {flex:1 1 220px;min-width:0;width:100%;}
      .audio-study .time-view:focus-visible {outline:3px solid #6366f1;outline-offset:3px;}
      .audio-study {position:relative;display:grid;grid-template-columns:minmax(0,1fr) 310px;gap:16px;align-items:start;}
      .audio-study.chat-collapsed {grid-template-columns:minmax(0,1fr) 44px;}
      .audio-study .player-main {min-width:0;}
      .audio-study .chat-panel {position:sticky;top:12px;border:1px solid #dfe3ef;border-radius:12px;background:#f8faff;overflow:hidden;}
      .audio-study .chat-header {display:flex;align-items:center;justify-content:space-between;gap:8px;padding:10px;}
      .audio-study .chat-header h3 {margin:0;font-size:16px;}
      .audio-study .chat-list {height:400px;max-height:60vh;overflow-y:auto;padding:12px;overflow-wrap:anywhere;}
      .audio-study .chat-entry {padding:10px 0;border-bottom:1px solid #e1e5ef;white-space:pre-wrap;}
      .audio-study .chat-entry p {margin:6px 0;}
      .audio-study .comment-attachments {display:grid;gap:10px;margin-top:10px;}
      .audio-study .comment-attachment {border:1px solid #dfe3ef;border-radius:8px;padding:8px;background:white;overflow-wrap:anywhere;}
      .audio-study .attachment-preview {display:block;max-width:100%;max-height:380px;object-fit:contain;margin:8px auto;}
      .audio-study .attachment-controls {display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
      .audio-study .pending-attachment {display:flex;align-items:center;gap:8px;margin:5px 0;}
      .audio-study .comment-time {padding:5px 9px;border:1px solid #cbd1e4;border-radius:6px;background:#f7f8ff;color:#243047;cursor:pointer;font:inherit;font-weight:600;}
      .audio-study .comment-time:hover {background:#e0e7ff;border-color:#818cf8;}
      .audio-study .comment-time:focus-visible {outline:2px solid #6366f1;outline-offset:2px;}
      .audio-study.chat-collapsed .chat-body,.audio-study.chat-collapsed .chat-header h3 {display:none;}
      .audio-study.chat-collapsed .chat-header {padding:0;}
      .audio-study .chat-toggle {min-width:44px;min-height:44px;}
      @media(max-width:700px) {
        .audio-study {grid-template-columns:minmax(0,1fr) 44px;}
        .audio-study:not(.chat-collapsed) .chat-panel {position:absolute;right:0;top:0;z-index:3;width:min(310px,90%);box-shadow:-6px 4px 20px #17203322;}
      }
      .audio-study .transcript {margin:16px 0;border:1px solid #dfe3ef;border-radius:12px;padding:12px;}
      .audio-study .transcript h3 {margin:0 0 8px;}
      .audio-study .transcript-body {position:relative;max-height:300px;overflow:auto;line-height:2;overflow-wrap:anywhere;}
      .audio-study .transcript-word {font:inherit;border:0;background:transparent;color:inherit;padding:2px 3px;cursor:pointer;border-radius:4px;}
      .audio-study .transcript-word.active {background:#c7d2fe;color:#172033;box-shadow:0 0 0 2px #6366f1;}
      .audio-study .transcript-copy.copy-success {background:#dcfce7 !important;border-color:#16a34a !important;color:#166534 !important;}
      .audio-study .transcript-copy.copy-error {background:#fff1f2 !important;border-color:#e11d48 !important;color:#9f1239 !important;}
      .audio-study .transcript-word:focus-visible {outline:2px solid #6366f1;}
      .audio-study {display:block;}
      .audio-study .listening-panels {display:grid;grid-template-columns:minmax(0,1fr) 310px;gap:16px;align-items:start;margin:12px 0;}
      .audio-study.chat-collapsed .listening-panels {grid-template-columns:minmax(0,1fr) 44px;}
      .audio-study .listening-panels .transcript {margin:0;}
      .audio-study .listening-panels .chat-panel {position:relative;top:0;}
      .audio-study .transcript-body {max-height:400px;}
      .audio-study .transcript-toolbar {display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:10px 0;}
      .audio-study .transcript-toolbar button[aria-pressed="true"] {background:#e0e7ff !important;border-color:#6366f1 !important;}
      .audio-study .transcript-word {user-select:none;touch-action:pan-y;}
      .audio-study .transcript-word.saved-highlight {background:#fef08a;color:#422006;}
      .audio-study .transcript-word.commented {text-decoration:underline;text-decoration-color:#8b5cf6;text-decoration-thickness:2px;}
      .audio-study .transcript-word.selected {background:#ddd6fe;color:#312e81;box-shadow:inset 0 -2px #7c3aed;}
      .audio-study .transcript-word.active {outline:2px solid #6366f1;}
      .audio-study.transcript-compact .transcript-body {max-height:120px;line-height:1.6;}
      .audio-study.transcript-compact .transcript-body br {display:none;}
      .audio-study.transcript-compact .chat-list,.audio-study.transcript-collapsed .chat-list {height:120px;max-height:120px;}
      .audio-study.transcript-collapsed .transcript-content {display:none;}
      .audio-study .selected-passage {margin:8px 0;color:#596579;overflow-wrap:anywhere;}
      .audio-study .highlight-list {max-height:120px;overflow:auto;}
      .audio-study .highlight-item {display:flex;align-items:center;gap:8px;margin:6px 0;}
      .audio-study .highlight-item .highlight-jump {text-align:left;flex:1;overflow-wrap:anywhere;}
      .audio-study .chat-entry.in-range {background:#ede9fe;border-left:3px solid #8b5cf6;padding-left:8px;}
      .audio-study blockquote {margin:8px 0;padding:6px 10px;border-left:3px solid #a78bfa;background:#f5f3ff;white-space:pre-wrap;overflow-wrap:anywhere;}
      .audio-study .note-quote:not([hidden]) {display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;}
      .audio-study .comment-delete {float:right;cursor:pointer;border:1px solid #cbd1e4;border-radius:6px;background:white;color:#9f1239;padding:4px 8px;}
      .audio-study .help-control {cursor:pointer;border:1px solid #b7c3dc;border-radius:7px;background:white;color:#263858;padding:7px 11px;margin:0 6px 4px 0;font:inherit;}
      .audio-study .help-control:disabled {opacity:.55;cursor:wait;}
      .audio-study .help-status {font-weight:600;color:#425577;}
      .audio-study article[data-tutor="gemini"] {border-left-color:#4285f4 !important;}
      .audio-study article[data-tutor="openai"] {border-left-color:#10a37f !important;}
      .audio-study.is-transcript-fullscreen {position:fixed !important;inset:0;z-index:2147483647;width:100vw;height:100vh;height:100dvh;box-sizing:border-box;overflow:hidden;padding:16px !important;border:0 !important;border-radius:0 !important;background:#fff !important;}
      .audio-study.is-transcript-fullscreen .player-main {display:flex;flex-direction:column;height:100%;min-height:0;}
      .audio-study.is-transcript-fullscreen .player-main > :not(.transport):not(canvas):not(.listening-panels) {display:none !important;}
      .audio-study.is-transcript-fullscreen .transport {flex:none;}
      .audio-study.is-transcript-fullscreen .player-main > canvas {display:block;flex:none;height:72px !important;margin:10px 0;}
      .audio-study.is-transcript-fullscreen .listening-panels {display:flex;flex:1;min-height:0;margin:0;}
      .audio-study.is-transcript-fullscreen .listening-panels .chat-panel {display:none !important;}
      .audio-study.is-transcript-fullscreen .listening-panels .transcript {display:flex;flex:1;flex-direction:column;min-width:0;min-height:0;}
      .audio-study.is-transcript-fullscreen .transcript-content {display:flex;flex:1;flex-direction:column;min-height:0;}
      .audio-study.is-transcript-fullscreen .transcript-body {flex:1;min-height:0;max-height:none !important;width:100%;box-sizing:border-box;align-self:center;padding:12px clamp(8px,4vw,64px);font-size:17px;line-height:1.9 !important;}
      .audio-study.is-transcript-fullscreen .transcript-body br {display:inline !important;}
      .audio-study.is-transcript-fullscreen .transcript-collapse-toggle,.audio-study.is-transcript-fullscreen .selected-passage,.audio-study.is-transcript-fullscreen .transcript-actions,.audio-study.is-transcript-fullscreen .highlight-message,.audio-study.is-transcript-fullscreen .saved-highlights {display:none !important;}
      .audio-study.is-transcript-fullscreen .transcript-help {margin:4px 0;}
      @media(max-width:700px) {
        .audio-study .listening-panels {grid-template-columns:minmax(0,1fr);}
        .audio-study.chat-collapsed .listening-panels {grid-template-columns:minmax(0,1fr) 44px;}
        .audio-study:not(.chat-collapsed) .listening-panels .chat-panel {position:relative;width:auto;box-shadow:none;}
      }
    </style><div class="player-main"><div class="completion-bar">
      <span class="completion-badge" role="status"></span>
      <button class="completion-toggle" type="button" title="You can mark this complete even if you listened elsewhere, or mark it incomplete again. Your choice is saved.">Mark complete</button>
      <span class="completion-message" role="status" aria-live="polite"></span>
      </div><div class="transport"><audio preload="metadata" hidden></audio>
      <button class="play-toggle" type="button" aria-label="Play">▶ Play</button>
      <button class="rewind" type="button" aria-label="Rewind 10 seconds">↶ 10s</button>
      <button class="forward" type="button" aria-label="Forward 10 seconds">10s ↷</button>
      <button class="stop" type="button" aria-label="Stop and return to the beginning">■ Stop</button>
      <label>Speed <select class="playback-speed" aria-label="Playback speed"><option value="0.5">0.5×</option><option value="0.75">0.75×</option><option value="1" selected>1×</option><option value="1.25">1.25×</option><option value="1.5">1.5×</option><option value="1.75">1.75×</option><option value="2">2×</option><option value="2.5">2.5×</option><option value="3">3×</option></select></label>
      <label>Volume <input class="volume" aria-label="Volume" type="range" min="0" max="1" step="0.05" value="1" style="width:90px"></label>
      <button class="time-view" type="button" title="Switch between elapsed time, time remaining, percent completed and percent remaining">
        <span class="time-label" style="display:block;font-size:12px;color:#596579"></span>
        <span class="time-value" style="display:block;font-size:18px;font-weight:650;font-variant-numeric:tabular-nums"></span>
        <span style="display:block;font-size:11px;color:#596579">Click to switch view ↻</span>
      </button></div>
      <p class="play-count" role="status"></p>
      <p class="hint">Click or drag on the waveform to move through the recording. Dragging also selects a range for a comment.</p>
      <canvas height="120" style="width:100%;height:64px;touch-action:none" aria-label="Audio position. Use arrow keys to seek." role="slider" tabindex="0" aria-valuemin="0"></canvas>
      <p class="selection" role="status"></p><div class="surfaced" aria-live="polite"></div>
      <p class="progress" role="status" aria-live="polite"></p>
      <section class="transcript" aria-label="Interactive transcript">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px"><h3>Transcript</h3><label><input class="copy-timestamps" type="checkbox" checked> Include timestamps in copy</label><button class="transcript-copy" type="button" title="Copy entire transcript" aria-label="Copy entire transcript">Copy transcript</button></div><span class="transcript-copy-status" role="status" aria-live="polite"></span><label><input class="transcript-follow" type="checkbox" checked> Follow playback</label>
        <div class="transcript-toolbar" role="group" aria-label="Transcript mode">
          <button class="transcript-mode" data-mode="navigate" type="button" aria-pressed="true">Navigate</button>
          <button class="transcript-mode" data-mode="highlight" type="button" aria-pressed="false">Highlight</button>
          <button class="transcript-mode" data-mode="comment" type="button" aria-pressed="false">Comment on passage</button>
          <button class="transcript-compact-toggle" type="button" aria-pressed="false">Flatten transcript</button>
          <button class="transcript-collapse-toggle" type="button" aria-expanded="true">Collapse transcript</button>
          <button class="transcript-fullscreen-toggle" type="button" aria-pressed="false">Full screen transcript</button>
        </div>
        <div class="transcript-content"><p class="transcript-help"></p><div class="transcript-body"></div>
          <p class="selected-passage" role="status"></p>
          <div class="transcript-actions"><button class="highlight-save" type="button" disabled>Save highlight</button> <button class="passage-comment" type="button" disabled>Comment on selection</button> <button class="selection-clear" type="button">Clear selection</button></div>
          <p class="highlight-message" role="status" aria-live="polite"></p>
          <details class="saved-highlights"><summary>My highlights</summary><div class="highlight-list"></div></details>
        </div>
      </section>
      <button class="mark">Add note at selection</button>
      <section class="composer" hidden style="margin-top:16px;padding:16px;border:2px solid #6366f1;border-radius:12px;background:#f4f5ff">
        <h3 style="margin:0 0 8px">Write a comment</h3><p class="note-time"></p><blockquote class="note-quote" hidden></blockquote>
        <label style="display:block;font-weight:700">Your note or comment
        <textarea class="note-text" rows="4" placeholder="Type your comment about this part of the recording…" style="display:block;box-sizing:border-box;width:100%;margin:8px 0;padding:12px;border:2px solid #818cf8;border-radius:8px;background:white;color:#172033;font:inherit"></textarea></label>
        <label style="display:block;margin:12px 0">Attach pictures or slides
          <input class="note-files" type="file" multiple accept=".png,.jpg,.jpeg,.gif,.webp,.pdf,.pptx" style="display:block;margin-top:6px">
        </label><p style="font-size:12px">Up to 5 files · 10 MB each · 25 MB total. PDF slides preview here; PowerPoint files download to view.</p>
        <div class="note-attachments"></div><p class="attachment-message" role="status" aria-live="polite"></p>
        <label>Review status <select class="note-status"><option>Neutral</option><option>Red</option><option>Yellow</option><option>Green</option></select></label>
        <p><button class="note-save">Save comment</button> <button class="note-cancel">Cancel</button></p>
        <p class="note-message" role="status" aria-live="polite"></p>
      </section>
      <section class="manual-tutor-composer" hidden style="margin:16px 0;padding:16px;border:1px solid #a5b4fc;border-radius:10px;background:#f5f7ff">
        <h3>Paste a tutor response</h3><p class="manual-tutor-context"></p>
        <p>This saves an answer you copied from another app. No AI request is sent.</p>
        <label>Tutor profile <select class="manual-tutor-profile"></select></label>
        <label style="display:block;margin-top:12px">Response from your AI chat<textarea class="manual-tutor-text" rows="7" style="display:block;box-sizing:border-box;width:100%;padding:10px;font:inherit" placeholder="Paste the response here…"></textarea></label>
        <p><button class="manual-tutor-save" type="button">Save response</button> <button class="manual-tutor-cancel" type="button">Cancel</button></p>
        <p class="manual-tutor-message" role="status" aria-live="polite"></p>
      </section>
      <p class="error" role="alert"></p><div class="notes"></div></div>
      <aside class="chat-panel" aria-label="Timestamped comment replay">
        <div class="chat-header"><h3>Comment replay</h3><button class="chat-toggle" type="button" aria-expanded="true" aria-label="Collapse comment replay">›</button></div>
        <div class="chat-body"><p style="margin:0;padding:0 12px;font-size:12px;color:#596579">Comments appear at their start time. Passage comments stay active across their range.</p>
        <div class="chat-list" role="log" aria-live="polite" aria-relevant="additions"></div></div>
      </aside>`;
    root.style.cssText='font:14px system-ui;color:#243047;padding:16px;border:1px solid #dfe3ef;border-radius:16px;background:#fff';
    for(const button of root.querySelectorAll('button'))button.style.cssText='padding:9px 14px;border:1px solid #cbd1e4;border-radius:8px;background:#f7f8ff;color:#243047;cursor:pointer';
    const panels=document.createElement('div');panels.className='listening-panels';
    const transcript=root.querySelector('.transcript');transcript.before(panels);
    panels.append(transcript,root.querySelector('.chat-panel'));
    root.deleteButton=mark=>{
      const button=document.createElement('button');button.type='button';button.className='comment-delete';button.textContent='×';
      button.title='Delete comment';button.setAttribute('aria-label','Delete comment');
      button.disabled=Boolean(root.deleteRequest);
      button.onclick=()=>{
        root.deleteRequest=crypto.randomUUID();
        for(const item of root.querySelectorAll('.comment-delete'))item.disabled=true;
        root.send('delete_note',{id:root.deleteRequest,mark_id:mark.id});
      };
      return button;
    };
    root.noteAttachments=[];
    root.paintPendingAttachments=()=>{
      const list=root.querySelector('.note-attachments');list.replaceChildren();
      root.noteAttachments.forEach((file,index)=>{
        const item=document.createElement('div');item.className='pending-attachment';
        const name=document.createElement('span');name.textContent=`${file.name} (${(file.size/1024/1024).toFixed(1)} MB)`;
        const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.setAttribute('aria-label',`Remove ${file.name}`);
        remove.disabled=Boolean(root.noteRequest);
        remove.onclick=()=>{if(root.noteRequest)return;root.noteAttachments.splice(index,1);root.paintPendingAttachments();};
        item.append(name,remove);list.append(item);
      });
    };
    root.querySelector('.note-files').onchange=e=>{
      if(root.noteRequest)return;
      const files=[...root.noteAttachments,...e.target.files];
      const message=root.querySelector('.attachment-message');e.target.value='';
      if(files.length>5){message.textContent='Attach up to 5 files per comment.';return;}
      if(files.some(file=>!file.size||file.size>10*1024*1024)){message.textContent='Each file must contain data and be 10 MB or smaller.';return;}
      if(files.reduce((sum,file)=>sum+file.size,0)>25*1024*1024){message.textContent='Attachments must total 25 MB or less.';return;}
      if(files.some(file=>! /\.(png|jpe?g|gif|webp|pdf|pptx)$/i.test(file.name))){message.textContent='Choose a picture, PDF, or PowerPoint (.pptx) file.';return;}
      root.noteAttachments=files;message.textContent='';root.paintPendingAttachments();
    };
    root.attachmentPageRequests=new Map();
    root.renderAttachments=(mark,container)=>{
      if(!mark.attachments?.length)return;
      const list=document.createElement('div');list.className='comment-attachments';
      for(const file of mark.attachments){
        const item=document.createElement('section');item.className='comment-attachment';
        const title=document.createElement('strong');title.textContent=file.name;item.append(title);
        if(file.preview_url){
          const picture=document.createElement('img');picture.className='attachment-preview';picture.loading='lazy';picture.src=file.preview_url;
          picture.alt=file.mime==='application/pdf'?`${file.name}, slide ${file.preview_page+1}`:file.name;
          const fullSize=document.createElement('a');fullSize.href=file.preview_url;fullSize.target='_blank';fullSize.rel='noopener noreferrer';fullSize.title='Open full-size preview';fullSize.append(picture);item.append(fullSize);
        }
        if(file.mime==='application/pdf'&&file.pages>1){
          const controls=document.createElement('div');controls.className='attachment-controls';
          const current=file.preview_page||0;
          if(root.attachmentPageRequests.get(file.id)===current)root.attachmentPageRequests.delete(file.id);
          const busy=root.attachmentPageRequests.has(file.id);
          const previous=document.createElement('button');previous.type='button';previous.textContent='← Previous';previous.disabled=current===0||busy;
          const next=document.createElement('button');next.type='button';next.textContent='Next →';next.disabled=current>=file.pages-1||busy;
          const label=document.createElement('span');label.textContent=`Slide ${current+1} of ${file.pages}`;
          const change=page=>{root.attachmentPageRequests.set(file.id,page);previous.disabled=true;next.disabled=true;label.textContent='Loading slide…';root.send('attachment_page',{id:file.id,page});};
          previous.onclick=()=>change(current-1);next.onclick=()=>change(current+1);
          controls.append(previous,label,next);item.append(controls);
        }
        if(file.preview_error){const message=document.createElement('p');message.textContent=file.preview_error;item.append(message);}
        const download=document.createElement('a');download.href=file.url;download.download=file.name;download.textContent=file.mime.endsWith('presentationml.presentation')?'Download PowerPoint':'Download file';item.append(download);
        list.append(item);
      }
      container.append(list);
    };
    root.audio = root.querySelector('audio'); root.canvas = root.querySelector('canvas');
    const setChatCollapsed=collapsed=>{
      root.classList.toggle('chat-collapsed',collapsed);
      const button=root.querySelector('.chat-toggle');
      button.textContent=collapsed?'‹':'›';
      button.setAttribute('aria-expanded',String(!collapsed));
      button.setAttribute('aria-label',collapsed?'Expand comment replay':'Collapse comment replay');
    };
    let collapsed=window.matchMedia?.('(max-width:700px)').matches||false;
    try {const saved=window.localStorage.getItem('studyforge.audio.chatCollapsed');if(saved!==null)collapsed=saved==='1';} catch {}
    setChatCollapsed(collapsed);
    root.querySelector('.chat-toggle').onclick=()=>{
      const next=!root.classList.contains('chat-collapsed');setChatCollapsed(next);
      try {window.localStorage.setItem('studyforge.audio.chatCollapsed',next?'1':'0');} catch {}
      root.paint();
    };
    root.paintChat=()=>{
      const position=root.audio.currentTime||0;
      const visible=root.marks.filter(m=>!m.is_deleted&&m.start<=position).sort((a,b)=>a.start-b.start||a.id-b.id);
      const signature=JSON.stringify([visible,visible.filter(m=>m.end>m.start&&position<=m.end).map(m=>m.id)]);
      if(signature===root.chatSignature)return;
      const list=root.querySelector('.chat-list');
      const follow=position<(root.chatPosition||0)||list.scrollHeight-list.scrollTop-list.clientHeight<60;
      root.chatSignature=signature;root.chatPosition=position;
      list.replaceChildren();
      if(!visible.length){const empty=document.createElement('p');empty.textContent='Comments will appear here as you listen.';list.append(empty);}
      for(const mark of visible){
        const card=document.createElement('div');card.className='chat-entry';
        card.classList.toggle('in-range',mark.end>mark.start&&position<=mark.end);
        const meta=document.createElement('strong');
        const timestamp=root.commentTimestamp(mark);
        meta.append(timestamp,document.createTextNode(` · ${mark.author||'You'}${mark.parent_id?' · Reply':''}`));
        const text=document.createElement('p');text.textContent=mark.note;
        if(mark.can_edit)card.append(root.deleteButton(mark));
        card.append(meta);
        if(mark.quote){const quote=document.createElement('blockquote');quote.textContent=mark.quote;card.append(quote);}
        card.append(text);root.renderAttachments(mark,card);list.append(card);
      }
      if(follow)list.scrollTop=list.scrollHeight;
    };
    root.timeMode=0;
    try {const saved=Number(window.localStorage.getItem('studyforge.audio.timeView'));if(Number.isInteger(saved)&&saved>=0&&saved<4)root.timeMode=saved;} catch {}
    root.querySelector('.time-view').onclick=()=>{
      root.timeMode=(root.timeMode+1)%4;
      try {window.localStorage.setItem('studyforge.audio.timeView',String(root.timeMode));} catch {}
      root.paint();
    };
    root.session = crypto.randomUUID(); root.seq = 0; root.pending = []; root.ranges = []; root.seconds = 0;
    root.selection = [0,0]; root.last = null; root.marks = [];
    root.processed=Number(data.progress?.position)||0;
    root.resume=Number(data.progress?.position)||0;
    root.explicitSelection=false;
    root.playId=null;root.observedPosition=root.resume;
    root.format=value=>`${Math.floor(value/60)}:${String(Math.floor(value%60)).padStart(2,'0')}`;
    root.rangeLabel=mark=>root.format(mark.start)+(mark.end>mark.start?` – ${root.format(mark.end)}`:'');
    root.seekToComment=mark=>{
      const audio=root.audio;
      if(!Number.isFinite(audio.duration)||audio.duration<=0)return;
      root.last=null;
      audio.currentTime=Math.max(0,Math.min(audio.duration,mark.start));
      root.processed=audio.currentTime;
      root.selection=[audio.currentTime,Math.max(audio.currentTime,Math.min(audio.duration,mark.end))];
      root.explicitSelection=true;root.wordSelection=null;root.selectedQuote=mark.quote||'';
      root.querySelector('.selection').textContent=`Selection: ${root.rangeLabel({start:root.selection[0],end:root.selection[1]})}`;
      root.retargetComposer();root.flush();
    };
    root.commentTimestamp=(mark,label=root.rangeLabel(mark))=>{
      const button=document.createElement('button');button.type='button';button.className='comment-time';button.textContent=label;
      button.title=`Jump to ${root.format(mark.start)}`;
      button.setAttribute('aria-label',`Jump to comment at ${root.rangeLabel(mark)}`);
      button.onclick=()=>root.seekToComment(mark);
      return button;
    };
    root.transcriptMode='navigate';root.wordSelection=null;root.highlights=[];
    const preference=(key,value)=>{try {window.localStorage.setItem('studyforge.audio.'+key,value);} catch {}};
    const setMode=mode=>{
      root.transcriptMode=mode;
      for(const button of root.querySelectorAll('.transcript-mode'))button.setAttribute('aria-pressed',String(button.dataset.mode===mode));
      root.paint();
    };
    for(const button of root.querySelectorAll('.transcript-mode'))button.onclick=()=>setMode(button.dataset.mode);
    const setCompact=compact=>{
      root.classList.toggle('transcript-compact',compact);
      root.querySelector('.transcript-compact-toggle').setAttribute('aria-pressed',String(compact));
      root.querySelector('.transcript-compact-toggle').textContent=compact?'Expand transcript layout':'Flatten transcript';
    };
    const setTranscriptCollapsed=collapsed=>{
      root.classList.toggle('transcript-collapsed',collapsed);
      root.querySelector('.transcript-collapse-toggle').setAttribute('aria-expanded',String(!collapsed));
      root.querySelector('.transcript-collapse-toggle').textContent=collapsed?'Show transcript':'Collapse transcript';
    };
    const fullscreenButton=root.querySelector('.transcript-fullscreen-toggle');
    const fullscreenDocument=root.ownerDocument;
    const setTranscriptFocus=active=>{
      if(root.classList.contains('is-transcript-fullscreen')===active)return;
      if(active){root.focusWasCollapsed=root.classList.contains('transcript-collapsed');setTranscriptCollapsed(false);}
      else if(root.focusWasCollapsed)setTranscriptCollapsed(true);
      root.classList.toggle('is-transcript-fullscreen',active);
      fullscreenButton.setAttribute('aria-pressed',String(active));
      fullscreenButton.textContent=active?'Exit full screen':'Full screen transcript';
      if(!active&&root.focusFallback){fullscreenDocument.body.style.overflow=root.focusPreviousBodyOverflow;root.focusFallback=false;}
      root.paint?.();
    };
    const startFullscreenFallback=()=>{
      if(!root.classList.contains('is-transcript-fullscreen')||root.focusFallback)return;
      root.focusPreviousBodyOverflow=fullscreenDocument.body.style.overflow;
      fullscreenDocument.body.style.overflow='hidden';
      root.focusFallback=true;
    };
    root.clearTranscriptFocus=()=>setTranscriptFocus(false);
    root.exitTranscriptFocus=()=>{
      if(root.focusNative&&fullscreenDocument.fullscreenElement===root){
        try {Promise.resolve(fullscreenDocument.exitFullscreen()).catch(()=>setTranscriptFocus(false));}
        catch {setTranscriptFocus(false);}
      } else setTranscriptFocus(false);
    };
    root.onTranscriptFullscreenChange=()=>{
      if(fullscreenDocument.fullscreenElement===root)root.focusNative=true;
      else if(root.focusNative){root.focusNative=false;setTranscriptFocus(false);}
      root.paint?.();
    };
    root.onTranscriptEscape=event=>{if(event.key==='Escape'&&root.focusFallback)root.exitTranscriptFocus();};
    fullscreenDocument.addEventListener('fullscreenchange',root.onTranscriptFullscreenChange);
    fullscreenDocument.addEventListener('keydown',root.onTranscriptEscape);
    fullscreenButton.onclick=()=>{
      if(root.classList.contains('is-transcript-fullscreen')){root.exitTranscriptFocus();return;}
      setTranscriptFocus(true);
      if(typeof root.requestFullscreen!=='function'){startFullscreenFallback();return;}
      try {Promise.resolve(root.requestFullscreen()).then(()=>{
        if(!root.classList.contains('is-transcript-fullscreen'))fullscreenDocument.exitFullscreen?.();
        else root.focusNative=fullscreenDocument.fullscreenElement===root;
      }).catch(startFullscreenFallback);}
      catch {startFullscreenFallback();}
    };
    try {setCompact(window.localStorage.getItem('studyforge.audio.transcriptCompact')==='1');setTranscriptCollapsed(window.localStorage.getItem('studyforge.audio.transcriptCollapsed')==='1');} catch {}
    root.querySelector('.transcript-compact-toggle').onclick=()=>{const next=!root.classList.contains('transcript-compact');setCompact(next);preference('transcriptCompact',next?'1':'0');};
    root.querySelector('.transcript-collapse-toggle').onclick=()=>{const next=!root.classList.contains('transcript-collapsed');setTranscriptCollapsed(next);preference('transcriptCollapsed',next?'1':'0');};
    root.selectWords=(anchor,end)=>{
      root.wordSelection=[Math.min(anchor,end),Math.max(anchor,end)];root.wordAnchor=anchor;
      const words=root.transcriptWords.slice(root.wordSelection[0],root.wordSelection[1]+1);
      root.selection=[words[0].start,words.at(-1).end];root.explicitSelection=true;
      root.selectedQuote=words.map(w=>w.text).join(' ');
      root.retargetComposer?.();
      root.querySelector('.selection').textContent=`Selection: ${root.rangeLabel({start:root.selection[0],end:root.selection[1]})}`;
      root.paint();
    };
    root.clearWordSelection=()=>{root.wordSelection=null;root.wordAnchor=undefined;root.selectedQuote='';root.explicitSelection=false;root.retargetComposer?.();root.paint();};
    root.querySelector('.selection-clear').onclick=root.clearWordSelection;
    root.querySelector('.passage-comment').onclick=()=>root.querySelector('.mark').click();
    root.querySelector('.highlight-save').onclick=()=>{
      if(!root.wordSelection||root.highlightRequest)return;
      root.highlightRequest=crypto.randomUUID();root.querySelector('.highlight-message').textContent='Saving highlight…';
      root.send('highlight_change',{id:root.highlightRequest,start:root.selection[0],end:root.selection[1],quote:root.selectedQuote});root.paint();
    };
    root.finishWordDrag=()=>{root.wordDrag=null;};
    root.ownerDocument.addEventListener('pointerup',root.finishWordDrag);
    root.ownerDocument.addEventListener('pointercancel',root.finishWordDrag);
    const audio = root.audio;
    const mediaSrc = resolveAudioSource(data.src, window.location.pathname);
    audio.src = mediaSrc;
    root.retargetComposer=()=>{
      if(root.querySelector('.composer').hidden||root.noteRequest)return;
      root.replyTo=null;
      root.noteRange=root.explicitSelection?[...root.selection]:[audio.currentTime,audio.currentTime];
      root.noteQuote=root.selectedQuote||'';
      root.querySelector('.composer h3').textContent='Write a comment';
      root.querySelector('.note-status').parentElement.hidden=false;
      root.querySelector('.note-time').textContent=`Comment at ${root.rangeLabel({start:root.noteRange[0],end:root.noteRange[1]})}`;
      root.querySelector('.note-quote').textContent=root.noteQuote;root.querySelector('.note-quote').title=root.noteQuote;root.querySelector('.note-quote').hidden=!root.noteQuote;
      root.querySelector('.note-message').textContent='';
    };
    const seek=position=>{
      if(!Number.isFinite(audio.duration))return;
      root.last=null;audio.currentTime=Math.max(0,Math.min(audio.duration,position));
      root.processed=audio.currentTime;root.explicitSelection=false;root.wordSelection=null;root.selectedQuote='';root.paint();
      root.retargetComposer();
    };
    root.querySelector('.completion-toggle').onclick=()=>{
      if(root.completionRequest)return;
      root.completionRequest=crypto.randomUUID();
      root.querySelector('.completion-toggle').disabled=true;
      root.querySelector('.completion-message').textContent='Saving…';
      root.send('completion_change',{id:root.completionRequest,completed:!root.completionState?.completed});
    };
    root.querySelector('.play-toggle').onclick=async()=>{
      if(!audio.paused){audio.pause();return;}
      try {await audio.play();}catch {root.querySelector('.error').textContent='Playback could not start. Try again.';}
    };
    root.querySelector('.rewind').onclick=()=>seek(audio.currentTime-10);
    root.querySelector('.forward').onclick=()=>seek(audio.currentTime+10);
    root.querySelector('.stop').onclick=()=>{audio.pause();seek(0);};
    root.querySelector('.playback-speed').onchange=e=>{root.last=null;audio.playbackRate=Number(e.target.value);};
    root.querySelector('.volume').oninput=e=>{audio.volume=Number(e.target.value);};
    root.canvas.onkeydown=e=>{
      if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){
        e.preventDefault();seek(e.key==='Home'?0:e.key==='End'?audio.duration:audio.currentTime+(e.key==='ArrowLeft'?-5:5));
      }
    };
    const send = () => root.send('events', [...root.pending]);
    root.flush = () => {
      if (!Number.isFinite(audio.duration) || audio.duration <= 0) return;
      root.processed=audio.currentTime;
      root.pending.push({session:root.session,sequence:root.seq++,duration:audio.duration,seconds:root.seconds,ranges:root.ranges,
        position:audio.currentTime,processed_until:Math.min(audio.duration,root.processed),play_id:root.playId});
      root.seconds = 0; root.ranges = []; send();
      root.paint();
    };
    const sample = () => {
      const now = performance.now(), pos = audio.currentTime;
      if (root.last) {
        const elapsed = (now-root.last.wall)/1000, delta = pos-root.last.pos;
        if (delta > 0 && elapsed > 0 && elapsed < 3 && delta <= elapsed*audio.playbackRate+0.4) {
          root.seconds += Math.min(elapsed,delta/audio.playbackRate);
          const lastRange = root.ranges[root.ranges.length-1];
          if(lastRange && Math.abs(lastRange[1]-root.last.pos)<.05) lastRange[1]=pos;
          else root.ranges.push([root.last.pos,pos]);
        }
      }
      root.last = !audio.paused && !audio.seeking ? {wall:now,pos} : null;
      root.processed=pos;root.observedPosition=pos;
      root.paint();
    };
    audio.addEventListener('play',()=>{if(!root.playId)root.playId=crypto.randomUUID();root.last={wall:performance.now(),pos:audio.currentTime};root.paint();});
    audio.addEventListener('timeupdate',sample);
    audio.addEventListener('seeking',()=>{root.beforeSeek=root.observedPosition;root.last=null;});
    audio.addEventListener('seeked',()=>{
      const restart=audio.currentTime<1 && (root.beforeSeek??root.observedPosition)>=1;
      root.processed=audio.currentTime;root.flush();
      if(restart)root.playId=audio.paused?null:crypto.randomUUID();
      root.observedPosition=audio.currentTime;root.paint();
      root.beforeSeek=undefined;
    });
    audio.addEventListener('pause',()=>{sample();root.flush();});
    audio.addEventListener('ended',()=>{root.flush();root.playId=null;});
    audio.addEventListener('error',()=>root.querySelector('.error').textContent='This audio could not be played. Try an MP3 or WAV export.');
    audio.addEventListener('loadedmetadata',()=>{audio.currentTime=Math.min(root.resume,audio.duration);root.flush();root.paint();});
    root.querySelector('.mark').onclick=()=>{
      if(root.noteRequest)return;
      root.replyTo=null;
      if(!root.explicitSelection)root.selection=[audio.currentTime,audio.currentTime];
      root.noteRange=[...root.selection];
      root.noteQuote=root.selectedQuote||'';
      root.querySelector('.note-quote').textContent=root.noteQuote;root.querySelector('.note-quote').title=root.noteQuote;root.querySelector('.note-quote').hidden=!root.noteQuote;
      root.querySelector('.composer h3').textContent='Write a comment';
      root.querySelector('.note-status').parentElement.hidden=false;
      root.querySelector('.composer').hidden=false;
      root.querySelector('.note-time').textContent=`Comment at ${root.format(root.noteRange[0])} – ${root.format(root.noteRange[1])}`;
      root.querySelector('.note-message').textContent='';
      const input=root.querySelector('.note-text');input.focus();input.scrollIntoView?.({block:'nearest',behavior:'smooth'});
    };
    root.querySelector('.note-cancel').onclick=()=>{root.querySelector('.composer').hidden=true;};
    root.querySelector('.manual-tutor-cancel').onclick=()=>{if(!root.tutorReplyRequest)root.querySelector('.manual-tutor-composer').hidden=true;};
    root.querySelector('.manual-tutor-save').onclick=()=>{
      if(root.tutorReplyRequest)return;
      const text=root.querySelector('.manual-tutor-text').value;
      if(!text.trim()){root.querySelector('.manual-tutor-message').textContent='Paste a response before saving.';return;}
      root.tutorReplyRequest=crypto.randomUUID();root.querySelector('.manual-tutor-save').disabled=true;
      root.querySelector('.manual-tutor-message').textContent='Saving response…';
      root.send('tutor_reply',{id:root.tutorReplyRequest,parent_id:root.tutorReplyTo,provider:root.querySelector('.manual-tutor-profile').value,text});
    };
    root.querySelector('.note-save').onclick=async()=>{
      if(root.noteRequest)return;
      const text=root.querySelector('.note-text').value.trim();
      if(!text&&!root.noteAttachments.length){root.querySelector('.note-message').textContent='Type a comment or attach a file before saving.';root.querySelector('.note-text').focus();return;}
      root.noteRequest=crypto.randomUUID();root.querySelector('.note-save').disabled=true;root.querySelector('.note-files').disabled=true;root.paintPendingAttachments();
      root.querySelector('.note-message').textContent='Saving comment…';
      try {
        const attachments=root.noteAttachments.length?await Promise.all(root.noteAttachments.map(file=>new Promise((resolve,reject)=>{
          const reader=new window.FileReader();reader.onload=()=>resolve({name:file.name,data:String(reader.result).split(',')[1]});
          reader.onerror=reader.onabort=()=>reject(new Error('The attachment could not be read. Choose it again.'));reader.readAsDataURL(file);
        }))):[];
        root.flush();
        root.send('note',{id:root.noteRequest,start:root.noteRange[0],end:root.noteRange[1],text,status:root.querySelector('.note-status').value,parent_id:root.replyTo,quote:root.noteQuote||'',attachments});
      } catch {
        root.noteRequest=null;root.querySelector('.note-save').disabled=false;root.querySelector('.note-files').disabled=false;root.paintPendingAttachments();
        root.querySelector('.note-message').textContent='An attachment could not be read. Choose the file again.';
      }
    };
    const point=e=>Math.max(0,Math.min(audio.duration||0,(e.clientX-root.canvas.getBoundingClientRect().left)/root.canvas.getBoundingClientRect().width*(audio.duration||0)));
    root.canvas.onpointerdown=e=>{root.drag=point(e);root.canvas.setPointerCapture(e.pointerId);};
    root.canvas.onpointerup=e=>{
      if(root.drag===undefined)return;
      const end=point(e); root.selection=[Math.min(root.drag,end),Math.max(root.drag,end)];
      root.explicitSelection=true;
      root.wordSelection=null;root.selectedQuote='';
      if(Math.abs(end-root.drag)<.6)root.selection=[end,end];
      audio.currentTime=end;
      root.drag=undefined;root.paint();
      root.retargetComposer();
      root.querySelector('.selection').textContent=`Selection: ${root.selection[0].toFixed(1)} – ${root.selection[1].toFixed(1)} seconds`;
    };
    root.querySelector('.transcript-copy').onclick=async()=>{
      const copyText=root.transcriptExports?.[root.querySelector('.copy-timestamps').checked?'timed':'plain']??root.transcriptText;
      const status=root.querySelector('.transcript-copy-status');
      const button=root.querySelector('.transcript-copy');
      if(root.copyBusy)return;
      clearTimeout(root.copyResetTimer);
      root.copyBusy=true;button.disabled=true;
      button.classList.remove('copy-success','copy-error');button.textContent='Copying…';status.textContent='';
      try {
        if(navigator.clipboard?.writeText)await navigator.clipboard.writeText(copyText);
        else {
          const focused=document.activeElement;
          const field=document.createElement('textarea');field.value=copyText;
          field.style.cssText='position:fixed;left:-9999px;top:0';root.append(field);field.select();
          let copied=false;
          try {copied=document.execCommand('copy');} finally {field.remove();focused?.focus();}
          if(!copied)throw new Error('Clipboard unavailable');
        }
        button.textContent='✓ Copied';button.classList.add('copy-success');
        status.textContent='Copied! ';
      } catch {
        button.textContent='Copy failed';button.classList.add('copy-error');
        status.textContent='Copy could not access your clipboard. Download the transcript from Transcript options. ';
      } finally {
        root.copyBusy=false;button.disabled=!root.transcriptText?.trim();
        root.copyResetTimer=setTimeout(()=>{
          button.textContent='Copy transcript';button.classList.remove('copy-success','copy-error');
        },2000);
      }
    };
    root.paintTranscript=()=>{
      root.querySelector('.transcript-copy').disabled=Boolean(root.copyBusy)||!root.transcriptText?.trim();
      const signature=JSON.stringify([root.transcriptText,root.speechWords,audio.duration]);
      if(signature!==root.transcriptSignature){
        root.transcriptSignature=signature;
        root.querySelector('.transcript-copy-status').textContent='';
        const timeline=root.speechWords?.length?{words:root.speechWords,timed:true,aligned:true}:transcriptTimeline(root.transcriptText,audio.duration);
        root.transcriptWords=timeline.words;root.activeWord=null;
        root.decorationSignature=null;
        root.wordSelection=null;root.selectedQuote='';root.wordDrag=null;
        const body=root.querySelector('.transcript-body');body.replaceChildren();
        root.transcriptHasWords=Boolean(timeline.words.length);
        root.transcriptHelp=timeline.aligned?'Click a word to jump there and add a note. Transcript and word timings are generated from speech.':timeline.timed?'Click a word to seek and add a note. Word timing is estimated within timestamped passages.':'Estimated timing from plain text. Click a word to seek and add a note.';
        let previousCue=-1;
        root.wordButtons=timeline.words.map((word,index)=>{
          if(previousCue!==word.cue && previousCue!==-1)body.append(document.createElement('br'));
          previousCue=word.cue;
          const button=document.createElement('button');button.type='button';button.className='transcript-word';button.textContent=word.text;
          button.title=`Jump to ${root.format(word.start)}`;
          button.onpointerdown=e=>{
            if(root.transcriptMode==='navigate'||e.button!==0)return;
            e.preventDefault();root.wordDrag=e.shiftKey&&root.wordAnchor!==undefined?root.wordAnchor:index;
            root.selectWords(root.wordDrag,index);
          };
          button.onpointerenter=()=>{if(root.wordDrag!==null&&root.wordDrag!==undefined)root.selectWords(root.wordDrag,index);};
          button.onkeydown=e=>{
            if(root.transcriptMode==='navigate')return;
            if(e.shiftKey&&['ArrowLeft','ArrowRight'].includes(e.key)){
              e.preventDefault();const next=Math.max(0,Math.min(root.wordButtons.length-1,index+(e.key==='ArrowLeft'?-1:1)));
              root.selectWords(root.wordAnchor??index,next);root.wordButtons[next].focus();
            }
          };
          button.onclick=e=>{
            if(root.transcriptMode!=='navigate'){
              if(e.detail===0||!root.wordSelection)root.selectWords(e.shiftKey?(root.wordAnchor??index):index,index);
              else if(e.shiftKey)root.selectWords(root.wordAnchor??index,index);
              if(root.transcriptMode==='comment')root.querySelector('.mark').click();
              return;
            }
            root.last=null;audio.currentTime=word.start;root.processed=word.start;
            root.wordSelection=null;root.selectedQuote=word.text;
            root.selection=[word.start,word.start];root.explicitSelection=true;
            root.retargetComposer();
            root.querySelector('.selection').textContent=`Selection: ${root.format(word.start)}`;
            root.paint();
          };
          body.append(button,document.createTextNode(' '));return button;
        });
      }
      const modeHelp=root.transcriptMode==='navigate'?root.transcriptHelp:'Drag across words, or select a word and Shift-click the last word. Shift + arrow keys also extend the selection. '+(root.transcriptMode==='highlight'?'Save a highlight or comment on it.':'Comment on the selected passage.');
      root.querySelector('.transcript-help').textContent=root.transcriptHasWords?modeHelp:root.transcriptText?.trim()?'Transcript will appear when audio finishes loading.':root.transcriptionStatus==='empty'?'No speech was detected in this recording.':root.transcriptionStatus==='error'?(root.transcriptionError||'Automatic transcription failed. Retry in Transcript options.'):'Generating transcript automatically… You can keep listening.';
      const decorations=JSON.stringify([root.wordSelection,root.highlights,root.marks]);
      if(decorations!==root.decorationSignature){
      root.decorationSignature=decorations;
      root.wordButtons?.forEach((button,i)=>{
        const word=root.transcriptWords[i];
        button.classList.toggle('selected',Boolean(root.wordSelection&&i>=root.wordSelection[0]&&i<=root.wordSelection[1]));
        button.classList.toggle('saved-highlight',root.highlights.some(h=>word.start<h.end&&word.end>h.start));
        button.classList.toggle('commented',root.marks.some(m=>!m.parent_id&&!m.is_deleted&&m.quote&&word.start<m.end&&word.end>m.start));
      });
      }
      root.querySelector('.transcript-actions').hidden=root.transcriptMode==='navigate'&&!root.wordSelection;
      root.querySelector('.selected-passage').textContent=root.wordSelection?`${root.rangeLabel({start:root.selection[0],end:root.selection[1]})} · “${root.selectedQuote.length>220?root.selectedQuote.slice(0,220)+'…':root.selectedQuote}”`:'';
      root.querySelector('.highlight-save').disabled=!root.wordSelection||Boolean(root.highlightRequest);
      root.querySelector('.passage-comment').disabled=!root.wordSelection||Boolean(root.noteRequest);
      const index=root.transcriptWords.findIndex(word=>audio.currentTime>=word.start && audio.currentTime<word.end);
      if(index===root.activeWord)return;
      if(root.activeWord>=0){root.wordButtons[root.activeWord]?.classList.remove('active');root.wordButtons[root.activeWord]?.removeAttribute('aria-current');}
      root.activeWord=index;
      if(index>=0){
        const button=root.wordButtons[index];button.classList.add('active');button.setAttribute('aria-current','true');
        const body=root.querySelector('.transcript-body');
        if(root.transcriptMode==='navigate'&&root.querySelector('.transcript-follow').checked && (button.offsetTop<body.scrollTop || button.offsetTop+button.offsetHeight>body.scrollTop+body.clientHeight))body.scrollTop=Math.max(0,button.offsetTop-body.clientHeight/2);
      }
    };
    root.paint = () => {
      root.paintTranscript();
      const position=audio.currentTime||0;
      root.querySelector('.surfaced').textContent=root.marks.filter(m=>!m.parent_id&&!m.is_deleted&&position>=m.start&&position<=(m.end>m.start?m.end:m.start+4)).map(m=>m.note).join(' · ');
      const toggle=root.querySelector('.play-toggle');toggle.textContent=audio.paused?'▶ Play':'Ⅱ Pause';toggle.setAttribute('aria-label',audio.paused?'Play':'Pause');
      root.canvas.setAttribute('aria-valuemax',String(Number.isFinite(audio.duration)?audio.duration:0));
      root.canvas.setAttribute('aria-valuenow',String(audio.currentTime||0));
      root.paintChat();
      const display=progressDisplay(audio.currentTime,audio.duration,root.timeMode);
      root.querySelector('.time-label').textContent=progressModes[root.timeMode];
      root.querySelector('.time-value').textContent=display;
      root.querySelector('.time-view').setAttribute('aria-label',`${progressModes[root.timeMode]}: ${display}. Switch to ${progressModes[(root.timeMode+1)%4]}`);
      const canvas=root.canvas, width=Math.max(300,Math.floor(canvas.clientWidth)); canvas.width=width;
      const ctx=canvas.getContext('2d'), duration=audio.duration||1;
      ctx.fillStyle='#f4f5fc';ctx.fillRect(0,0,width,120);
      ctx.fillStyle='#dcfce7';ctx.fillRect(0,0,root.processed/duration*width,120);
      const colors={Red:'#ef444466',Yellow:'#eab30866',Green:'#22c55e66',Neutral:'#94a3b866'};
      for(const m of root.marks){if(m.parent_id||m.is_deleted)continue;ctx.fillStyle=colors[m.status];ctx.fillRect(m.start/duration*width,108,Math.max(3,(m.end-m.start)/duration*width),12);}
      if(root.peaks)root.peaks.forEach((p,i)=>{ctx.fillStyle=i/root.peaks.length*duration<=root.processed?'#16a34a':'#6864c8';ctx.fillRect(i/root.peaks.length*width,60-p*50,Math.max(1,width/root.peaks.length-1),Math.max(2,p*100));});
      ctx.fillStyle='#6366f133';ctx.fillRect(root.selection[0]/duration*width,0,(root.selection[1]-root.selection[0])/duration*width,120);
      ctx.fillStyle='#222';ctx.fillRect(audio.currentTime/duration*width,0,2,120);
      const saved=root.pending.length===0 && Math.abs(root.processed-(root.savedPosition||0))<.1;
      root.querySelector('.progress').textContent=`${saved?'✓ Saved':'Auto-saving'} · ${display}. Green follows your position in either direction.`;
    };
    const context = new (window.AudioContext || window.webkitAudioContext)();
    fetch(mediaSrc).then(r=>r.arrayBuffer()).then(b=>context.decodeAudioData(b)).then(buffer=>{
      const samples=buffer.getChannelData(0), count=700, size=Math.max(1,Math.ceil(samples.length/count));
      root.peaks=Array.from({length:count},(_,i)=>{let peak=0;for(let j=i*size;j<Math.min((i+1)*size,samples.length);j++)peak=Math.max(peak,Math.abs(samples[j]));return peak;});root.paint();
    }).catch(()=>{root.querySelector('.error').textContent='Waveform decoding is unavailable for this file. Playback and time-based notes are still available.';}).finally(()=>context.close());
    root.tick=()=>{if(!audio.paused){sample();root.flush();}};
  }
  root.send=setStateValue;
  clearInterval(root.timer);
  root.timer=setInterval(root.tick,2000);
  if(data.ack?.session===root.session)root.pending=root.pending.filter(e=>e.sequence>data.ack.sequence);
  root.savedPosition=Number(data.progress?.position)||0;
  root.querySelector('.play-count').textContent=`▶ ${data.play_count||0} plays · ${data.marks.filter(m=>!m.is_deleted).length} comments and replies`;
  if(data.note_result && data.note_result.id===root.noteRequest && root.handledNoteResult!==data.note_result.id){
    root.handledNoteResult=data.note_result.id;
    root.querySelector('.note-save').disabled=false;
    root.querySelector('.note-message').textContent=data.note_result.error||'✓ Comment saved. It appears in the conversation below.';
    root.noteRequest=null;root.querySelector('.note-files').disabled=false;
    if(!data.note_result.error){
      const hadAttachments=root.noteAttachments.length>0;root.noteAttachments=[];root.querySelector('.note-files').value='';root.querySelector('.attachment-message').textContent='';root.paintPendingAttachments();
      if(hadAttachments)root.send('note',null);
      root.querySelector('.note-text').value='';root.explicitSelection=false;root.wordSelection=null;root.selectedQuote='';
      root.replyTo=null;root.noteQuote='';root.querySelector('.composer').hidden=true;
    } else root.paintPendingAttachments();
  }
  if(data.delete_result && data.delete_result.id===root.deleteRequest){
    root.deleteRequest=null;
    root.querySelector('.error').textContent=data.delete_result.error||'';
    for(const button of root.querySelectorAll('.comment-delete'))button.disabled=false;
  }
  root.completionState=data.completion||{completed:false};
  const completionButton=root.querySelector('.completion-toggle');
  completionButton.textContent=root.completionState.completed?'Mark incomplete':'Mark complete';
  completionButton.disabled=Boolean(root.completionRequest);
  const badge=root.querySelector('.completion-badge');
  badge.textContent=root.completionState.completed?'✓ Complete':'○ Incomplete';
  badge.classList.toggle('is-complete',Boolean(root.completionState.completed));
  badge.title=root.completionState.source==='manual'?'Your saved manual choice':root.completionState.completed?'At least 95% listened':'Completes automatically after at least 95% is listened to. You can also mark it complete manually.';
  if(data.completion_result && data.completion_result.id===root.completionRequest){
    root.completionRequest=null;completionButton.disabled=false;
    root.querySelector('.completion-message').textContent=data.completion_result.error||'✓ Saved';
  }
  root.speechWords=data.transcription?.words||[];
  root.transcriptionStatus=data.transcription?.status;root.transcriptionError=data.transcription?.error;
  root.transcriptText=data.transcript||'';
  root.transcriptExports=data.transcript_exports;
  if(data.tutor_reply_result&&data.tutor_reply_result.id===root.tutorReplyRequest){
    root.tutorReplyRequest=null;root.querySelector('.manual-tutor-save').disabled=false;
    root.querySelector('.manual-tutor-message').textContent=data.tutor_reply_result.error||'✓ Response saved.';
    if(!data.tutor_reply_result.error){root.querySelector('.manual-tutor-text').value='';root.querySelector('.manual-tutor-composer').hidden=true;}
  }
  root.marks=data.marks;
  root.highlights=data.highlights||[];
  if(data.highlight_result&&data.highlight_result.id===root.highlightRequest){
    root.highlightRequest=null;
    root.querySelector('.highlight-message').textContent=data.highlight_result.error||'✓ Highlight saved.';
  }
  const highlightSignature=JSON.stringify(root.highlights);
  if(highlightSignature!==root.highlightSignature){
    root.highlightSignature=highlightSignature;
    const list=root.querySelector('.highlight-list');list.replaceChildren();
    root.querySelector('.saved-highlights summary').textContent=`My highlights (${root.highlights.length})`;
    for(const highlight of root.highlights){
      const item=document.createElement('div');item.className='highlight-item';
      const jump=document.createElement('button');jump.type='button';jump.className='highlight-jump';
      jump.textContent=`${root.rangeLabel(highlight)} · ${highlight.quote.length>100?highlight.quote.slice(0,100)+'…':highlight.quote}`;jump.title=highlight.quote;
      jump.onclick=()=>{
        root.audio.currentTime=highlight.start;root.processed=highlight.start;
        const indices=root.transcriptWords.map((w,i)=>w.start<highlight.end&&w.end>highlight.start?i:-1).filter(i=>i>=0);
        if(indices.length)root.selectWords(indices[0],indices.at(-1));
        root.paint();
      };
      const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.setAttribute('aria-label','Remove highlight');
      remove.onclick=()=>{if(root.highlightRequest)return;root.highlightRequest=crypto.randomUUID();root.send('highlight_change',{id:root.highlightRequest,delete_id:highlight.id});};
      item.append(jump,remove);list.append(item);
    }
  }
  // Leave the thread DOM alone during progress acknowledgments, preserving focus.
  if(data.help_result && data.help_result.id===root.helpRequest){
    root.helpRequest=null;root.threadSignature=null;
    root.querySelector('.error').textContent=data.help_result.error||'';
  }
  const signature=JSON.stringify([data.marks,data.manual_tutors,data.tutor_profiles]);
  if(signature!==root.threadSignature){
    root.threadSignature=signature;
    const notes=root.querySelector('.notes');notes.replaceChildren();
    const heading=document.createElement('h3');heading.textContent='Comments';notes.append(heading);
    if(data.manual_tutors){const hint=document.createElement('p');hint.textContent='Use Save tutor response to paste an answer from your AI chat. Find your collection in Tutor responses.';notes.append(hint);}
    const children=new Map();
    for(const mark of data.marks){const parent=mark.parent_id||0;if(!children.has(parent))children.set(parent,[]);children.get(parent).push(mark);}
    const renderThread=(mark,container,depth=0)=>{
      const card=document.createElement('article');card.style.cssText=`margin:12px 0 12px ${depth?16:0}px;padding:12px;border-left:3px solid #c7d2fe;background:#f8faff;border-radius:8px`;
      card.dataset.markId=String(mark.id);
      if(mark.tutor_provider)card.dataset.tutor=mark.tutor_provider;
      if(mark.can_edit && !mark.is_deleted)card.append(root.deleteButton(mark));
      const meta=document.createElement('div');meta.style.cssText='font-size:12px;color:#596579;margin-bottom:7px';
      meta.textContent=`${mark.author||'You'}${mark.tutor_kind==='manual'?' · Pasted response':mark.tutor_kind==='review'?' · Follow-up review':''}${mark.unread?' · New reply':''} · ${mark.created_at?mark.created_at+' UTC':'Earlier comment'}`;card.append(meta);
      const jump=root.commentTimestamp(mark,root.rangeLabel(mark)+(mark.parent_id?'':` · ${mark.status}`));card.append(jump);
      if(mark.quote&&!mark.is_deleted){const quote=document.createElement('blockquote');quote.textContent=mark.quote;card.append(quote);}
      const body=document.createElement('p');body.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere;margin:10px 0';
      if(mark.tutor_provider){
        let last=0;const pattern=/\[((?:\d+:)?\d{1,2}:\d{2})\]/g;
        for(const match of mark.note.matchAll(pattern)){
          body.append(document.createTextNode(mark.note.slice(last,match.index)));
          const seconds=match[1].split(':').reduce((n,v)=>n*60+Number(v),0);
          if(seconds<=root.audio.duration){const cite=document.createElement('button');cite.textContent=match[0];cite.onclick=()=>{root.audio.currentTime=seconds;root.processed=seconds;root.paint();};body.append(cite);}
          else body.append(document.createTextNode(match[0]));last=match.index+match[0].length;
        }body.append(document.createTextNode(mark.note.slice(last)));
      }else body.textContent=mark.note;
      card.append(body);root.renderAttachments(mark,card);
      if(!mark.parent_id&&mark.help_state&&!data.manual_tutors){
        const status=document.createElement('p');status.className='help-status';status.textContent=mark.help_state==='open'?'⚑ Help requested':mark.help_state==='resolved'?'✓ Resolved · tutoring stopped':'Tutor help not requested';card.append(status);
        const sendHelp=payload=>{if(root.helpRequest)return;root.helpRequest=crypto.randomUUID();root.send('help_change',{id:root.helpRequest,root_id:mark.id,...payload});for(const b of root.querySelectorAll('.help-control'))b.disabled=true;};
        if(mark.can_manage_help&&(mark.help_state==='open'||mark.can_request_help)){
          const flag=document.createElement('button');flag.className='help-control help-toggle';flag.textContent=mark.help_state==='open'?'Resolved / stop tutoring':mark.help_state==='inactive'?'Request tutor help':'Reopen tutor help';flag.disabled=Boolean(root.helpRequest);flag.onclick=()=>sendHelp({opened:mark.help_state!=='open'});card.append(flag);
        }
        if((children.get(mark.id)||[]).some(m=>m.unread)){
          const read=document.createElement('button');read.className='help-control mark-read';read.textContent='Mark replies read';read.disabled=Boolean(root.helpRequest);read.onclick=()=>sendHelp({read:true});card.append(read);
        }
        if(mark.help_state==='open')for(const job of mark.tutor_jobs||[]){
          const detail=document.createElement('p');detail.style.cssText='font-size:12px;color:#596579';
          const label=job.kind==='reply'?'First reply':'Review';
          const states={queued:data.tutors_enabled?`Scheduled for ${new Date(job.due_at*1000).toLocaleString()}`:'Waiting for API tutoring to be enabled',blocked:job.error,running:'Generating…',done:'Posted',quiet:'Reviewed · no follow-up needed',error:job.error,cancelled:'Stopped'};
          detail.textContent=`${label}: ${states[job.status]||job.status}${job.status==='queued'&&job.error?' · '+job.error:''}`;card.append(detail);
        }
      }
      const reply=document.createElement('button');reply.className='reply';reply.textContent='Reply';
      reply.onclick=()=>{
        root.replyTo=mark.id;root.noteRange=[mark.start,mark.end];
        root.noteQuote='';root.querySelector('.note-quote').hidden=true;
        root.querySelector('.composer').hidden=false;root.querySelector('.composer h3').textContent='Reply to '+(mark.author||'your comment');
        root.querySelector('.note-time').textContent=`At ${root.format(mark.start)} · ${mark.note.slice(0,140)}`;
        root.querySelector('.note-status').parentElement.hidden=true;root.querySelector('.note-message').textContent='';
        root.querySelector('.note-text').focus();root.querySelector('.composer').scrollIntoView?.({block:'nearest',behavior:'smooth'});
      };card.append(reply);container.append(card);
      if(data.manual_tutors&&mark.can_save_tutor_reply){
        const paste=document.createElement('button');paste.type='button';paste.className='help-control save-tutor-response';paste.textContent='Save tutor response';
        paste.onclick=()=>{
          if(root.tutorReplyRequest)return;
          root.tutorReplyTo=mark.id;
          const select=root.querySelector('.manual-tutor-profile');const previous=select.value;select.replaceChildren();
          for(const [provider,label] of Object.entries(data.tutor_profiles||{})){const option=document.createElement('option');option.value=provider;option.textContent=label;select.append(option);}
          if(Object.hasOwn(data.tutor_profiles||{},previous))select.value=previous;
          root.querySelector('.manual-tutor-context').textContent=`At ${root.format(mark.start)} · ${mark.note.slice(0,180)}`;
          root.querySelector('.manual-tutor-message').textContent='';root.querySelector('.manual-tutor-composer').hidden=false;
          root.querySelector('.manual-tutor-text').focus();root.querySelector('.manual-tutor-composer').scrollIntoView?.({block:'center',behavior:'smooth'});
        };card.append(paste);
      }
      for(const child of children.get(mark.id)||[])renderThread(child,depth<5?card:container,depth+1);
    };
    for(const mark of (children.get(0)||[]).sort((a,b)=>a.start-b.start||a.id-b.id))renderThread(mark,notes);
    if(!data.marks.length){const empty=document.createElement('p');empty.textContent='Start a conversation at any point in the recording.';notes.append(empty);}
  }
  if(data.focus_root&&root.focusedThread!==data.focus_root){
    const card=root.querySelector(`[data-mark-id="${Number(data.focus_root)}"]`);
    if(card){card.scrollIntoView?.({block:'center',behavior:'smooth'});root.focusedThread=data.focus_root;}
  }
  root.paint();
  if(!root.mixer)root.mixer=mountMusicMixer(root, data.music_scope||'default');
  root.mixer.update(data.music_tracks||[]);
  return ()=>{clearInterval(root.timer);queueMicrotask(()=>{if(!root.isConnected){root.exitTranscriptFocus?.();root.clearTranscriptFocus?.();root.ownerDocument.removeEventListener('fullscreenchange',root.onTranscriptFullscreenChange);root.ownerDocument.removeEventListener('keydown',root.onTranscriptEscape);root.ownerDocument.removeEventListener('pointerup',root.finishWordDrag);root.ownerDocument.removeEventListener('pointercancel',root.finishWordDrag);root.send=()=>{};root.audio.pause();root.mixer.dispose();}});};
}

// A second media element keeps music time, speed and events out of study telemetry.
export function mountMusicMixer(root, scope) {
  const content=root.audio, panel=document.createElement('section');
  panel.className='music-mixer';panel.setAttribute('aria-label','Background music track');
  const heading=document.createElement('h3');heading.textContent='01 · Content';
  root.querySelector('.transport').before(heading);
  panel.innerHTML=`<style>
    .audio-study .music-mixer {margin:12px 0;padding:16px;border:1px solid #a5b4fc;border-left:5px solid #6366f1;border-radius:12px;background:#f5f7ff;}
    .audio-study .music-mixer h3 {margin:0 0 12px;}
    .audio-study .mixer-row {display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:10px 0;}
    .audio-study .music-mixer select {max-width:100%;padding:6px;}
    .audio-study .music-mixer button {padding:9px 14px;border:1px solid #a5b4fc;border-radius:8px;background:white;color:#243047;cursor:pointer;}
    .audio-study .music-mixer button:disabled {opacity:.5;cursor:default;}
    .audio-study .music-track {width:min(100%,420px);}
    .audio-study .music-position {flex:1;min-width:120px;}
    @media(max-width:600px) {
      .audio-study .music-mixer {padding:12px;}
      .audio-study .transport button,.audio-study .music-mixer button,.audio-study select {min-height:44px;}
      .audio-study .music-mixer input[type=range] {min-height:36px;max-width:100%;}
      .audio-study .music-track {width:100%;min-width:0;}
      .audio-study .music-mixer select {font-size:16px;}
      .audio-study .music-keep {width:20px;height:20px;vertical-align:middle;}
    }
  </style><h3>02 · Background music</h3><audio class="music-audio" preload="metadata" hidden></audio>
  <div class="mixer-row"><label class="music-track">Track <select class="music-select" aria-label="Music track" style="width:100%"></select></label>
    <label>Loop <select class="music-loop" aria-label="Music loop mode"><option value="one">One beat</option><option value="playlist">Entire playlist</option></select></label></div>
  <div class="mixer-row"><button type="button" class="music-play">▶ Play music</button><button type="button" class="music-next">Next beat →</button>
    <label>Volume <input class="music-volume" aria-label="Music volume" type="range" min="0" max="1" step="0.05" value="0.3"><output class="music-volume-value">30%</output></label>
    <label>Speed <select class="music-speed" aria-label="Music speed"><option value="0.5">0.5×</option><option value="0.75">0.75×</option><option value="1" selected>1×</option><option value="1.25">1.25×</option><option value="1.5">1.5×</option><option value="1.75">1.75×</option><option value="2">2×</option></select></label></div>
  <div class="mixer-row"><input class="music-position" aria-label="Music position" type="range" min="0" max="100" step="0.1" value="0"><span class="music-time">0:00</span></div>
  <label><input class="music-keep" type="checkbox" checked> Keep music playing when content pauses or ends</label>
  <div class="mixer-row"><button type="button" class="mix-play">▶ Play both</button><button type="button" class="mix-pause">Ⅱ Pause both</button></div>
  <p class="music-message" role="status" aria-live="polite"></p>`;
  (root.querySelector('.progress')||root.querySelector('.transport')).after(panel);
  root.querySelector('.volume').setAttribute('aria-label','Content volume');
  root.querySelector('.playback-speed').setAttribute('aria-label','Content speed');
  const $=selector=>panel.querySelector(selector), music=$('.music-audio');
  let tracks=[],index=0,signature='',disposed=false,follow=false;
  let context=null,contentGain=null,musicGain=null;
  // Gain nodes support independent faders on phones that ignore media.volume.
  const volumes=()=>{
    const cv=Number(root.querySelector('.volume').value),mv=Number($('.music-volume').value);
    content.volume=contentGain?1:cv;music.volume=musicGain?1:mv;
    if(contentGain)contentGain.gain.value=cv;
    if(musicGain)musicGain.gain.value=mv;
  };
  const unlock=()=>{
    const Context=window.AudioContext||window.webkitAudioContext;
    if(!context&&Context?.prototype?.createMediaElementSource){
      context=new Context();
      contentGain=context.createGain();musicGain=context.createGain();
      context.createMediaElementSource(content).connect(contentGain).connect(context.destination);
      context.createMediaElementSource(music).connect(musicGain).connect(context.destination);
      volumes();
    }
    if(context&&context.state!=='running')context.resume().catch(()=>{
      $('.music-message').textContent='Tap Play again to enable audio on this device.';
    });
  };
  root.addEventListener('click',unlock,true);
  root.querySelector('.volume').oninput=volumes;
  const key=`study-music-mixer:${scope}`;
  try {
    const saved=JSON.parse(window.localStorage.getItem(key)||'{}');
    if(['one','playlist'].includes(saved.loop))$('.music-loop').value=saved.loop;
    if(typeof saved.keep==='boolean')$('.music-keep').checked=saved.keep;
    if(Number.isFinite(saved.volume)&&saved.volume>=0&&saved.volume<=1)$('.music-volume').value=saved.volume;
    if([...$('.music-speed').options].some(option=>Number(option.value)===saved.speed))$('.music-speed').value=saved.speed;
  }catch{}
  const settings=()=>{
    volumes();
    music.playbackRate=Number($('.music-speed').value);
    music.preservesPitch=true;
    music.loop=$('.music-loop').value==='one'||tracks.length===1;
    $('.music-volume-value').textContent=`${Math.round(Number($('.music-volume').value)*100)}%`;
    try{window.localStorage.setItem(key,JSON.stringify({volume:Number($('.music-volume').value),speed:music.playbackRate,loop:$('.music-loop').value,keep:$('.music-keep').checked}));}catch{}
  };
  const paint=()=>{
    $('.music-play').textContent=music.paused?'▶ Play music':'Ⅱ Pause music';
    const duration=Number.isFinite(music.duration)?music.duration:0;
    $('.music-position').max=duration||100;
    $('.music-position').value=music.currentTime||0;
    $('.music-position').disabled=!duration;
    const format=seconds=>`${Math.floor(seconds/60)}:${String(Math.floor(seconds%60)).padStart(2,'0')}`;
    $('.music-time').textContent=`${format(music.currentTime||0)} / ${format(duration)}`;
  };
  const start=async()=>{
    if(!tracks.length||disposed)return;
    $('.music-message').textContent='';
    try{await music.play();if(disposed)music.pause();}
    catch{if(!disposed)$('.music-message').textContent='Music could not play. Try Play music again, or select another file.';}
    paint();
  };
  const select=(next,resume=false)=>{
    music.pause();index=next;
    $('.music-message').textContent='';
    $('.music-select').value=String(index);
    music.src=resolveAudioSource(tracks[index].src,window.location.pathname);
    music.currentTime=0;settings();paint();
    if(resume)void start();
  };
  $('.music-play').onclick=()=>{if(music.paused){follow=true;void start();}else{follow=false;music.pause();paint();}};
  $('.music-next').onclick=()=>select((index+1)%tracks.length,!music.paused);
  $('.music-select').onchange=e=>select(Number(e.target.value),!music.paused);
  $('.music-volume').oninput=settings;
  $('.music-speed').onchange=settings;
  $('.music-loop').onchange=settings;
  $('.music-keep').onchange=()=>{settings();if(!$('.music-keep').checked&&content.paused){music.pause();paint();}};
  $('.music-position').oninput=e=>{music.currentTime=Number(e.target.value);paint();};
  $('.mix-play').onclick=()=>{
    follow=true;void start();
    // Start both directly from the click to retain browser user activation.
    content.play().catch(()=>{root.querySelector('.error').textContent='Content could not start. Try Play again.';});
  };
  $('.mix-pause').onclick=()=>{follow=false;content.pause();music.pause();paint();};
  music.addEventListener('ended',()=>{
    if(!tracks.length||disposed)return;
    select($('.music-loop').value==='playlist'?(index+1)%tracks.length:index,true);
  });
  music.addEventListener('error',()=>{$('.music-message').textContent='This music file could not be loaded or decoded. Select another track or upload a supported file.';paint();});
  for(const event of ['play','pause','timeupdate','loadedmetadata'])music.addEventListener(event,paint);
  const contentPause=()=>{if(!$('.music-keep').checked){music.pause();paint();}};
  const contentPlay=()=>{if(follow&&music.paused)void start();};
  content.addEventListener('pause',contentPause);content.addEventListener('ended',contentPause);content.addEventListener('play',contentPlay);
  settings();
  return {audio:music, update(incoming){
    const next=JSON.stringify(incoming);
    if(signature===next)return;
    signature=next;
    const previous=tracks[index],playing=!music.paused;
    tracks=incoming;
    $('.music-select').replaceChildren();
    tracks.forEach((track,i)=>{const option=document.createElement('option');option.value=String(i);option.textContent=`${i+1}. ${track.title}`;$('.music-select').append(option);});
    for(const selector of ['.music-select','.music-loop','.music-play','.music-next','.mix-play'])$(selector).disabled=!tracks.length;
    $('.music-next').disabled=tracks.length<2;
    if(!tracks.length){follow=false;music.pause();music.removeAttribute('src');music.load();$('.music-message').textContent='Upload music above, then choose a track or saved playlist.';paint();return;}
    const retained=tracks.findIndex(track=>track.id===previous?.id&&track.src===previous?.src);
    if(retained>=0){index=retained;$('.music-select').value=String(index);settings();}
    else select(0,playing);
  }, dispose(){disposed=true;music.pause();music.removeAttribute('src');music.load();root.removeEventListener('click',unlock,true);if(context)void context.close();content.removeEventListener('pause',contentPause);content.removeEventListener('ended',contentPause);content.removeEventListener('play',contentPlay);}};
}
