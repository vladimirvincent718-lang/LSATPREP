"""
voice_exam.py — Voice Exam Mode for StudyForge.  v2 (bug-fix release)

Root-cause fixes vs v1
───────────────────────
1. TTS cancel/pause broken on Chrome.
   Cause: calling window.parent.speechSynthesis.cancel() from an iframe
   is unreliable in Chrome (cross-context call). Fix: inject a <script>
   directly into window.parent.document.head so the TTS engine (_sfTTSEngine)
   runs natively in the parent window where speechSynthesis is reliable.

2. speakFeedback() restarted TTS after every mic start/stop.
   Fix: removed entirely.

3. Pause now implemented as "hardStop + remember position" because
   speechSynthesis.pause() is also unreliable in Chrome.

4. Close button / FAB ✕ didn't reliably close.
   Fix: S.destroyed flag + clean disconnect of MutationObserver.

5. Panel outlived the quiz.
   Fix: cleanup_voice_exam_panel() function + call it in exam pages
   when returning to the setup form / score screen.

6. Settings were hidden behind a toggle button.
   Fix: always visible in a settings row at the bottom of the panel.
"""

from __future__ import annotations
import json
import re

import streamlit.components.v1 as _components


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean(text: str | None) -> str:
    if not text:
        return ""
    t = re.sub(r"\*{1,2}|_{1,2}|`", "", str(text))
    return " ".join(t.split())


def build_question_data(q: dict, idx: int, total: int) -> dict:
    choices: dict[str, str] = {}
    for letter in ("A", "B", "C", "D", "E"):
        val = q.get(f"choice_{letter.lower()}", "")
        if val:
            choices[letter] = _clean(val)
    return {
        "idx":           idx,
        "total":         total,
        "stimulus":      _clean(q.get("stimulus", "")),
        "passage":       _clean(q.get("passage", "")),
        "section_type":  _clean(q.get("section_type", "")),
        "question_type": _clean(q.get("question_type", "")),
        "choices":       choices,
    }


# ── TTS engine source — injected as <script> into parent head ─────────────────
# Runs in native parent-window context so speechSynthesis.cancel() works.
# Must NOT use backtick characters (it gets embedded in a JS template literal).
#
# Key fixes for "events fire but no audio" bug on Chrome:
#  1. _stopGen counter — every stop() increments it; speak() stores the
#     value it saw at call-time.  The deferred ss.speak() only fires if
#     _stopGen hasn't changed, so a cancel() called between stop→speak
#     can never kill the new utterance.
#  2. 60 ms settle delay between ss.cancel() and ss.speak() — Chrome needs
#     a tick to flush its synthesis queue before accepting a new utterance.
#  3. Explicit u.volume = 1 — prevents silent-default-voice edge case.
#  4. Voice pre-selection with voiceschanged fallback — Chrome loads voices
#     asynchronously on first access; without this the engine may silently
#     use an uninitialised voice on the very first Play press.

_TTS_ENGINE_JS = """
(function(){
  if (window._sfTTSEngine && window._sfTTSEngine.version === 'direct-speak-v5') return;
  if (window._sfTTSEngine) {
    try { window._sfTTSEngine.stop(); } catch(e) {}
  }
  window._sfTTSEngine = {
    version: 'direct-speak-v5',
    _gen: 0,

    /* Cancel synchronously (no delayed side-effects). */
    _cancel: function() {
      var ss = window.speechSynthesis;
      if (!ss) return;
      try { ss.cancel(); } catch(e){}
      try { ss.cancel(); } catch(e){}
    },

    /* Full stop: cancel now + one safety cancel after 120 ms IF no new
       speak() has been requested in the meantime. */
    stop: function() {
      var gen = ++this._gen;
      this._cancel();
      var self = this;
      setTimeout(function(){
        if (self._gen === gen) { self._cancel(); }
      }, 120);
    },

    /* Speak text.  Increments _gen so any pending delayed cancel from a
       previous stop() call is invalidated.  Waits 60 ms for the sync
       cancel to flush before calling ss.speak(). */
    speak: function(text, rate, stateKey) {
      var gen = ++this._gen;   /* invalidate any pending delayed stop */
      this._cancel();           /* flush previous utterance */
      var ss  = window.speechSynthesis;
      if (!ss || !text) return;

      var u = new SpeechSynthesisUtterance(text);
      u.rate   = parseFloat(rate) || 1.0;
      u.volume = 1.0;
      u.lang   = 'en-US';

      u.onboundary = function(e) {
        var S = window[stateKey];
        if (S && e.name === 'word') {
          S.charIdx = (S._speakOffset || 0) + (e.charIndex || 0);
          if (S._cbProgress) S._cbProgress();
        }
      };
      u.onend = function() {
        var S = window[stateKey];
        if (S && !S._shouldStop) {
          S.speaking = false; S.paused = false;
          S.charIdx  = S.fullText ? S.fullText.length : 0;
          if (S._cbEnd) S._cbEnd();
        }
      };
      u.onerror = function(ev) {
        var S = window[stateKey];
        if (S && ev.error !== 'interrupted') {
          S.speaking = false;
          if (S._cbError) S._cbError(ev.error);
        }
      };

      /* Pick the best available English voice explicitly so Chrome never
         falls back to an uninitialised or silent default voice. */
      function pickVoice() {
        var voices = ss.getVoices();
        return voices.find(function(v){ return v.lang === 'en-US' && v.localService; })
            || voices.find(function(v){ return v.lang === 'en-US'; })
            || voices.find(function(v){ return v.lang.startsWith('en'); })
            || voices[0]
            || null;
      }

      var self = this;
      function doSpeak() {
        /* Bail if a newer stop() or speak() has been called since we started. */
        if (self._gen !== gen) return;
        var v = pickVoice();
        if (v) u.voice = v;
        try { ss.speak(u); } catch(e) {}
      }

      /* Chrome loads voices asynchronously the first time. */
      if (ss.getVoices().length > 0) {
        /* Voices already available — still wait 60 ms for the cancel to clear. */
        doSpeak();
      } else {
        /* Wait for voiceschanged, then speak (with the same 60 ms settle). */
        var handler = function() {
          ss.removeEventListener('voiceschanged', handler);
          doSpeak();
        };
        ss.addEventListener('voiceschanged', handler);
        /* Safety: if the event never fires (some browsers), try after 1 s anyway. */
        setTimeout(function(){
          if (self._gen === gen && !ss.speaking) doSpeak();
        }, 1000);
      }
    }
  };
})();
"""


# ── CSS ───────────────────────────────────────────────────────────────────────
# No backticks allowed — embedded in a JS template literal.

_PANEL_CSS = """
#sf-vep-fab{position:fixed;bottom:88px;right:28px;z-index:99998;
  width:52px;height:52px;border-radius:50%;
  background:linear-gradient(135deg,#7C3AED 0%,#5B21B6 100%);
  color:#fff;border:none;cursor:pointer;font-size:22px;
  display:flex;align-items:center;justify-content:center;
  box-shadow:0 4px 18px rgba(124,58,237,.50);
  transition:transform .18s,box-shadow .18s;
  -webkit-tap-highlight-color:transparent;}
#sf-vep-fab:hover{transform:translateY(-2px);box-shadow:0 6px 24px rgba(124,58,237,.65);}
#sf-vep-fab:active{transform:scale(.93);}
#sf-vep-fab.sf-playing{
  background:linear-gradient(135deg,#0F766E 0%,#115E59 100%);
  box-shadow:0 4px 18px rgba(15,118,110,.45);}
#sf-vep-fab.sf-listening{
  background:linear-gradient(135deg,#DC2626 0%,#991B1B 100%);
  animation:sf-pulse 1.4s ease-in-out infinite;}
@keyframes sf-pulse{
  0%,100%{box-shadow:0 4px 18px rgba(220,38,38,.55);}
  50%{box-shadow:0 4px 36px rgba(220,38,38,.85),0 0 0 10px rgba(220,38,38,.12);}}
#sf-vep-panel{
  position:fixed;bottom:0;left:0;right:0;z-index:99997;
  background:rgba(13,13,23,.97);backdrop-filter:blur(18px);
  -webkit-backdrop-filter:blur(18px);
  border-top:1px solid rgba(255,255,255,.10);border-radius:18px 18px 0 0;
  color:#f0f0f0;font-family:-apple-system,BlinkMacSystemFont,sans-serif;
  font-size:14px;padding:14px 18px 22px;
  transform:translateY(100%);transition:transform .30s cubic-bezier(.4,0,.2,1);
  box-shadow:0 -8px 40px rgba(0,0,0,.45);max-width:900px;margin:0 auto;}
#sf-vep-panel.sf-open{transform:translateY(0);}
#sf-vep-panel.sf-collapsed{
  left:auto;right:92px;bottom:18px;width:min(360px,calc(100vw - 124px));
  padding:10px 12px;border-radius:14px;transform:translateY(0);}
#sf-vep-panel.sf-collapsed #sf-vep-header{margin-bottom:0;}
#sf-vep-panel.sf-collapsed #sf-vep-title{white-space:nowrap;}
#sf-vep-panel.sf-collapsed #sf-vep-status{text-align:left;}
#sf-vep-panel.sf-collapsed #sf-vep-pgwrap,
#sf-vep-panel.sf-collapsed #sf-vep-controls,
#sf-vep-panel.sf-collapsed #sf-vep-microw,
#sf-vep-panel.sf-collapsed #sf-vep-confirm,
#sf-vep-panel.sf-collapsed #sf-vep-settings-row{display:none !important;}
#sf-vep-header{display:flex;align-items:center;gap:10px;margin-bottom:11px;}
#sf-vep-title{font-size:12px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;
  color:#A78BFA;display:flex;align-items:center;gap:6px;}
#sf-vep-qlabel{font-size:12px;font-weight:400;color:#6B7280;margin-left:2px;}
#sf-vep-status{flex:1;font-size:12px;color:#9CA3AF;text-align:right;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
#sf-vep-collapse,#sf-vep-close{background:none;border:none;color:#6B7280;cursor:pointer;
  font-size:18px;line-height:1;padding:4px 8px;border-radius:6px;
  transition:color .15s,background .15s;flex-shrink:0;}
#sf-vep-collapse:hover,#sf-vep-close:hover{color:#f0f0f0;background:rgba(255,255,255,.09);}
#sf-vep-pgwrap{height:3px;background:rgba(255,255,255,.08);border-radius:2px;
  margin-bottom:12px;overflow:hidden;}
#sf-vep-pg{height:100%;background:linear-gradient(90deg,#7C3AED,#A78BFA);
  border-radius:2px;width:0%;transition:width .25s linear;}
#sf-vep-controls{display:flex;align-items:center;flex-wrap:wrap;gap:7px;margin-bottom:11px;}
.sf-btn{min-width:44px;min-height:44px;border-radius:10px;
  border:1px solid rgba(255,255,255,.13);background:rgba(255,255,255,.06);
  color:#e5e7eb;cursor:pointer;font-size:18px;
  display:inline-flex;align-items:center;justify-content:center;
  padding:0 10px;transition:background .14s,transform .1s;
  -webkit-tap-highlight-color:transparent;user-select:none;}
.sf-btn:hover{background:rgba(255,255,255,.13);}
.sf-btn:active{transform:scale(.92);}
.sf-btn:disabled{opacity:.35;cursor:default;transform:none;}
#sf-vep-speed{height:44px;background:rgba(255,255,255,.06);
  border:1px solid rgba(255,255,255,.13);color:#e5e7eb;border-radius:8px;
  padding:0 10px;font-size:13px;cursor:pointer;margin-left:auto;
  -webkit-appearance:none;appearance:none;}
#sf-vep-speed option{background:#0d0d17;color:#e5e7eb;}
#sf-vep-microw{display:flex;align-items:center;gap:10px;margin-bottom:12px;}
#sf-vep-mic{min-width:52px;min-height:52px;border-radius:50%;
  border:2px solid rgba(255,255,255,.18);background:rgba(255,255,255,.06);
  color:#e5e7eb;cursor:pointer;font-size:22px;
  display:flex;align-items:center;justify-content:center;
  flex-shrink:0;transition:all .2s;-webkit-tap-highlight-color:transparent;}
#sf-vep-mic:hover{background:rgba(255,255,255,.12);}
#sf-vep-mic:disabled{opacity:.35;cursor:default;}
#sf-vep-mic.sf-listening{background:rgba(220,38,38,.25);border-color:#EF4444;
  animation:sf-pulse 1.4s ease-in-out infinite;}
#sf-vep-transcript{flex:1;background:rgba(255,255,255,.04);
  border:1px solid rgba(255,255,255,.09);border-radius:10px;
  padding:10px 14px;font-size:13px;color:#9CA3AF;min-height:44px;
  display:flex;align-items:center;line-height:1.4;transition:border-color .2s;
  white-space:pre-line;}
#sf-vep-transcript.sf-active{border-color:rgba(239,68,68,.45);color:#e5e7eb;}
#sf-vep-confirm{display:none;background:rgba(124,58,237,.14);
  border:1px solid rgba(167,139,250,.35);border-radius:12px;
  padding:11px 14px;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:12px;}
#sf-vep-confirm-text{flex:1;font-size:14px;color:#C4B5FD;font-weight:500;}
.sf-cfbtn{padding:8px 18px;border-radius:8px;border:none;cursor:pointer;
  font-size:13px;font-weight:600;min-height:38px;min-width:88px;
  transition:background .15s,transform .1s;-webkit-tap-highlight-color:transparent;}
.sf-cfbtn:active{transform:scale(.94);}
#sf-vep-conf-yes{background:#7C3AED;color:#fff;}
#sf-vep-conf-yes:hover{background:#6D28D9;}
#sf-vep-conf-no{background:rgba(255,255,255,.09);color:#e5e7eb;
  border:1px solid rgba(255,255,255,.18) !important;}
#sf-vep-conf-no:hover{background:rgba(255,255,255,.16);}
#sf-vep-settings-row{display:grid;grid-template-columns:1fr 1fr;gap:8px 20px;
  padding-top:10px;border-top:1px solid rgba(255,255,255,.08);}
.sf-srow{display:flex;align-items:center;gap:8px;font-size:12px;
  color:#9CA3AF;cursor:pointer;user-select:none;}
.sf-srow input[type=checkbox]{width:15px;height:15px;cursor:pointer;
  accent-color:#7C3AED;flex-shrink:0;}
.sf-sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;
  overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;}
@media(max-width:600px){
  #sf-vep-panel{padding:12px 12px 16px;border-radius:14px 14px 0 0;}
  #sf-vep-panel.sf-collapsed{right:70px;bottom:14px;width:calc(100vw - 88px);
    padding:9px 10px;border-radius:12px;}
  .sf-btn{min-width:40px;min-height:40px;font-size:16px;}
  #sf-vep-settings-row{grid-template-columns:1fr;}
  #sf-vep-fab{bottom:82px;right:16px;width:46px;height:46px;font-size:19px;}}
"""


# ── Main JS bundle ────────────────────────────────────────────────────────────
# __QUESTION_DATA__ → replaced with JSON
# __TTS_ENGINE__    → replaced with backtick-quoted engine source
# __CSS__           → replaced with backtick-quoted CSS

_VOICE_JS = r"""
<script>
(function(){
'use strict';
var P=window.parent, doc=P&&P.document;
if(!P||!doc) return;

/* Question data */
var Q=__QUESTION_DATA__;
var V='settings-space-v5';

/* Keys */
var SK='_sfVoiceState', TK='_sfTTSEngine';

/* Feature detection */
var hasTTS=!!(P.speechSynthesis);
var SRC=P.SpeechRecognition||P.webkitSpeechRecognition;
var hasSTT=!!SRC;

/* ── Inject TTS engine into parent head ──────────────────────────────────── */
function ensureTTSEngine(){
  if(P[TK]&&P[TK].version==='direct-speak-v5') return;
  if(P[TK]){try{P[TK].stop();}catch(e){}P[TK]=null;}
  var old=doc.getElementById('sf-tts-engine');if(old)old.remove();
  var s=doc.createElement('script');
  s.id='sf-tts-engine';
  s.textContent=__TTS_ENGINE__;
  (doc.head||doc.documentElement).appendChild(s);
}

/* ── State ───────────────────────────────────────────────────────────────── */
if(!P[SK]){
  P[SK]={
    panelOpen:false, panelCollapsed:false, speaking:false, paused:false,
    _shouldStop:false, _pausedAt:0, _speakOffset:0,
    speed:1.0, fullText:'', charIdx:0,
    listening:false, recognition:null,
    autoRead:false, requireConfirm:true, showTranscript:true, voiceEnabled:true,
    pendingAnswer:null, currentIdx:-1, destroyed:false,
    _cbProgress:null, _cbEnd:null, _cbError:null,
  };
}
var S=P[SK];
S.destroyed=false;
if(S.version!==V){S.autoRead=false;S.version=V;S._forceStopOnBoot=true;}
if(typeof S.panelCollapsed==='undefined') S.panelCollapsed=false;
S._cbProgress=function(){updateProg();};
S._cbEnd=function(){setStatus('Finished');updateCtrl();updateProg();};
S._cbError=function(err){setStatus('TTS error: '+err);S.speaking=false;updateCtrl();};

var tts=null;

/* ── CSS ─────────────────────────────────────────────────────────────────── */
function ensureStyles(){
  if(doc.getElementById('sf-vep-style')) return;
  var s=doc.createElement('style');
  s.id='sf-vep-style';
  s.textContent=__CSS__;
  (doc.head||doc.documentElement).appendChild(s);
}

/* ── Panel HTML ──────────────────────────────────────────────────────────── */
function panelHTML(){
  var ns=hasSTT?'':' disabled';
  return '<div id="sf-vep-header">'
    +'<div id="sf-vep-title"><span>\uD83C\uDFA7</span><span>Voice Mode</span>'
    +'<span id="sf-vep-qlabel">Q '+(Q.idx+1)+' / '+Q.total+'</span></div>'
    +'<span id="sf-vep-status" role="status" aria-live="polite">Ready</span>'
    +'<button id="sf-vep-collapse" aria-label="Collapse voice panel" title="Collapse voice panel">\u2212</button>'
    +'<button id="sf-vep-close" aria-label="Close voice panel">\u2715</button></div>'
    +'<div id="sf-vep-pgwrap" aria-hidden="true"><div id="sf-vep-pg"></div></div>'
    +'<div id="sf-vep-controls" role="group" aria-label="Playback controls">'
    +'<button class="sf-btn" id="sf-vep-play" aria-label="Play">\u25B6</button>'
    +'<button class="sf-btn" id="sf-vep-pause" aria-label="Pause" disabled>\u23F8</button>'
    +'<button class="sf-btn" id="sf-vep-replay" aria-label="Replay">\uD83D\uDD04</button>'
    +'<button class="sf-btn" id="sf-vep-rewind" aria-label="Back to question">\u23EA</button>'
    +'<button class="sf-btn" id="sf-vep-skip" aria-label="Skip to choices">\u23E9</button>'
    +'<button class="sf-btn" id="sf-vep-stop" aria-label="Stop">\u23F9</button>'
    +'<select id="sf-vep-speed" aria-label="Reading speed">'
    +'<option value="0.75">0.75\xD7</option><option value="1" selected>1\xD7</option>'
    +'<option value="1.25">1.25\xD7</option><option value="1.5">1.5\xD7</option>'
    +'<option value="2">2\xD7</option></select></div>'
    +'<div id="sf-vep-microw">'
    +'<button id="sf-vep-mic" aria-label="Speak your answer"'+ns+'>\uD83C\uDF99</button>'
    +'<div id="sf-vep-transcript" role="status" aria-live="polite">'
    +(hasSTT?'Tap \uD83C\uDF99 then say A, B, C, or D':'\uD83D\uDEAB Speech recognition not supported')
    +'</div></div>'
    +'<div id="sf-vep-confirm" role="alertdialog">'
    +'<span id="sf-vep-confirm-text"></span>'
    +'<button class="sf-cfbtn" id="sf-vep-conf-yes">\u2713\u202FConfirm</button>'
    +'<button class="sf-cfbtn" id="sf-vep-conf-no">\u2715\u202FChange</button></div>'
    +'<div id="sf-vep-settings-row">'
    +'<label class="sf-srow"><input type="checkbox" id="sf-v-autoread"> Auto-play next question</label>'
    +'<label class="sf-srow"><input type="checkbox" id="sf-v-confirm"> Require confirmation</label>'
    +'<label class="sf-srow"><input type="checkbox" id="sf-v-transcript"> Show transcript</label>'
    +'<label class="sf-srow"><input type="checkbox" id="sf-v-voice"'+ns+'> Voice input</label>'
    +'</div>';
}

function ensureFAB(){
  var old=doc.getElementById('sf-vep-fab');
  if(old&&old.dataset.version===V) return;
  if(old) old.remove();
  var f=doc.createElement('button');
  f.id='sf-vep-fab';
  f.dataset.version=V;
  f.setAttribute('aria-label','Open voice settings');
  f.setAttribute('aria-expanded','false');
  f.setAttribute('title','Voice settings');
  f.innerHTML='\u2699';
  f.addEventListener('click',togglePanel);
  doc.body.appendChild(f);
}

function ensurePanel(){
  var old=doc.getElementById('sf-vep-panel');
  if(old&&old.dataset.version===V) return;
  if(old) old.remove();
  var p=doc.createElement('div');
  p.id='sf-vep-panel';
  p.dataset.version=V;
  p.setAttribute('role','region');
  p.setAttribute('aria-label','Voice Exam Controls');
  p.innerHTML=panelHTML();
  doc.body.appendChild(p);
  wirePanel(p);
}

function $(id){return doc.getElementById(id);}

function wirePanel(panel){
  if(panel.dataset.wired) return;
  panel.dataset.wired='1';

  $('sf-vep-close').addEventListener('click',function(){
    S.panelOpen=false; S.panelCollapsed=false; applyPanelState(); stopSTT();
  });
  $('sf-vep-collapse').addEventListener('click',function(){
    S.panelOpen=true; S.panelCollapsed=!S.panelCollapsed; applyPanelState();
    if(S.panelCollapsed){stopSTT(); setStatus('Collapsed');}
  });
  $('sf-vep-play').addEventListener('click',function(){
    S._shouldStop=false;
    if(S.paused){S.paused=false;speakFrom(S._pausedAt||0);}
    else speakQuestion();
  });
  $('sf-vep-pause').addEventListener('click',function(){
    if(!S.speaking) return;
    S._pausedAt=S.charIdx; S.paused=true;
    hardStop(); S._shouldStop=false;
    setStatus('Paused \u2014 press \u25B6 to resume'); updateCtrl();
  });
  $('sf-vep-replay').addEventListener('click',function(){
    S._shouldStop=false; hardStop(); speakQuestion();
  });
  $('sf-vep-rewind').addEventListener('click',function(){
    S._shouldStop=false; hardStop(); speakFrom(0);
  });
  $('sf-vep-skip').addEventListener('click',function(){
    S._shouldStop=false; hardStop(); speakChoices();
  });
  $('sf-vep-stop').addEventListener('click',function(){
    hardStop(); setStatus('Stopped \u2014 press \u25B6 to read again');
  });
  $('sf-vep-speed').addEventListener('change',function(e){
    S.speed=parseFloat(e.target.value);
    if(S.speaking){var p=S.charIdx;S._shouldStop=false;hardStop();speakFrom(p);}
  });
  $('sf-vep-mic').addEventListener('click',function(){
    if(S.listening) stopSTT();
    else if(S.voiceEnabled&&hasSTT) startSTT();
  });
  $('sf-vep-conf-yes').addEventListener('click',confirmAnswer);
  $('sf-vep-conf-no').addEventListener('click',cancelConfirm);
  $('sf-v-autoread').addEventListener('change',function(e){S.autoRead=e.target.checked;});
  $('sf-v-confirm').addEventListener('change',function(e){S.requireConfirm=e.target.checked;});
  $('sf-v-transcript').addEventListener('change',function(e){
    S.showTranscript=e.target.checked;
    var t=$('sf-vep-transcript');if(t)t.style.visibility=e.target.checked?'':'hidden';
  });
  $('sf-v-voice').addEventListener('change',function(e){S.voiceEnabled=e.target.checked;});
}

/* ── TTS ─────────────────────────────────────────────────────────────────── */
function buildFull(){
  var p=['Question '+(Q.idx+1)+' of '+Q.total+'.'];
  if(Q.section_type) p.push(Q.section_type+'.');
  if(Q.question_type) p.push(Q.question_type+'.');
  if(Q.passage) p.push('Passage. '+Q.passage);
  p.push(Q.stimulus);
  ['A','B','C','D','E'].forEach(function(l){if(Q.choices[l])p.push(l+'. '+Q.choices[l]);});
  return p.join('  ');
}
function buildQuestionOnly(){
  return (Q.stimulus||'').replace(/\s+/g,' ').trim();
}
function buildChoices(){
  var p=['Answer choices.'];
  ['A','B','C','D','E'].forEach(function(l){if(Q.choices[l])p.push(l+'. '+Q.choices[l]);});
  return p.join('  ');
}
function speakQuestion(){
  if(!hasTTS){setStatus('TTS not supported in this browser');return;}
  S.fullText=buildQuestionOnly(); S.charIdx=0; speakFrom(0);
}
function speakChoices(){
  if(!hasTTS) return;
  S.fullText=buildChoices(); S.charIdx=0; speakFrom(0); setStatus('Reading choices\u2026');
}
function speakFrom(charPos){
  if(!hasTTS||!tts) return;
  S._shouldStop=false; S._speakOffset=charPos;
  var text=(S.fullText||'').substring(charPos).trim();
  if(!text){setStatus('Finished');S.speaking=false;updateCtrl();return;}
  S.speaking=true; S.paused=false;
  setStatus('Reading\u2026'); updateCtrl();
  tts.speak(text,S.speed,SK);
}
function hardStop(){
  S._shouldStop=true;
  if(tts) tts.stop();
  S.speaking=false; S.paused=false; S.charIdx=0;
  updateCtrl();
}

/* ── STT ─────────────────────────────────────────────────────────────────── */
function startSTT(){
  if(!hasSTT||!S.voiceEnabled||S.listening) return;
  if(S.speaking){S._pausedAt=S.charIdx;S.paused=true;hardStop();S._shouldStop=false;}
  var recog=new SRC();
  recog.continuous=false; recog.interimResults=true;
  recog.lang='en-US'; recog.maxAlternatives=3;
  recog.onstart=function(){
    S.listening=true; setMicState(true);
    setStatus('Listening\u2026'); setTranscript('\uD83C\uDF99 Listening\u2026',true);
  };
  recog.onresult=function(ev){
    var interim='',final='';
    for(var i=ev.resultIndex;i<ev.results.length;i++){
      var t=ev.results[i][0].transcript;
      ev.results[i].isFinal?(final+=t):(interim+=t);
    }
    var shown=(final||interim).trim();
    if(shown) setTranscript('\uD83C\uDF99 \u201C'+shown+'\u201D',true);
    if(final) processVoice(final.trim());
  };
  recog.onerror=function(e){
    S.listening=false; setMicState(false);
    if(e.error==='no-speech')
      setTranscript('No speech detected.\nTap \uD83C\uDF99 to try again.');
    else if(e.error==='not-allowed')
      setTranscript('\uD83D\uDEAB Microphone blocked.\nAllow mic access in your browser settings then retry.');
    else if(e.error==='network')
      setTranscript('Network error — check connection.');
    else
      setTranscript('Mic error: '+e.error+'\nTap \uD83C\uDF99 to try again.');
    setStatus('Ready');
  };
  recog.onend=function(){
    S.listening=false; S.recognition=null; setMicState(false);
    if(!S._gotResult) setTranscript('Tap \uD83C\uDF99 to speak your answer');
    setStatus(S.paused?'Paused \u2014 press \u25B6 to resume':'Ready');
  };
  S.recognition=recog; S._gotResult=false;
  try{recog.start();}catch(err){
    S.listening=false;S.recognition=null;setMicState(false);
    setTranscript('Could not start mic: '+err.message);
  }
}
function stopSTT(){
  if(S.recognition){try{S.recognition.stop();}catch(e){}S.recognition=null;}
  S.listening=false; setMicState(false); setStatus('Ready');
}

/* ── Voice parsing ───────────────────────────────────────────────────────── */
function processVoice(text){
  var low=text.toLowerCase().replace(/[.,!?]/g,'').trim();
  S._gotResult=true;

  if(S.pendingAnswer){
    if(anyOf(low,['confirm','yes','yep','yeah','submit','correct','ok','right']))
      {confirmAnswer();return;}
    if(anyOf(low,['no','nope','change','different','cancel','wrong','wait']))
      {cancelConfirm();return;}
  }

  if(anyOf(low,['repeat','replay','read again','again','restart','reread','read the question']))
    {S._shouldStop=false;hardStop();speakQuestion();setTranscript('Replaying\u2026');return;}
  if(anyOf(low,['choices','read choices','answers','read answers','options']))
    {S._shouldStop=false;hardStop();speakChoices();setTranscript('Reading choices\u2026');return;}
  if(anyOf(low,['pause','stop reading','quiet','stop talking']))
    {S._pausedAt=S.charIdx;S.paused=true;hardStop();S._shouldStop=false;
     setStatus('Paused');setTranscript('Paused. Tap \u25B6 to resume.');return;}
  if(anyOf(low,['resume','continue','play','go']))
    {if(S.paused){S.paused=false;speakFrom(S._pausedAt||0);}
     setTranscript('Resuming\u2026');return;}
  if(anyOf(low,['next question','next','skip question']))
    {clickByText('Next \u25B6');clickByText('Next Question');
     setTranscript('Next question\u2026');return;}
  if(anyOf(low,['previous','go back','back','prev']))
    {clickByText('\u25C4 Prev');setTranscript('Going back\u2026');return;}
  if(anyOf(low,['submit','finish']))
    {clickByText('Submit Answer');setTranscript('Submitting\u2026');return;}

  var letter=detectAnswer(low);
  if(letter){
    setTranscript('\uD83C\uDF99 I heard: '+text);
    handleAnswer(letter);
    return;
  }

  setTranscript('\uD83E\uDD14 Didn\u2019t catch: \u201C'+text+'\u201D\nSay A, B, C, or D');
  setStatus('Try again');
}

function detectAnswer(text){
  var nato={alpha:'A',bravo:'B',charlie:'C',delta:'D',echo:'E',able:'A',baker:'B',dog:'D'};
  for(var n in nato){
    if(text.indexOf(n)!==-1&&Q.choices[nato[n]]) return nato[n];
  }
  var pats=[
    /^([a-e])$/,
    /\b(?:answer|choice|option|pick|select|letter)\s+([a-e])\b/,
    /\b([a-e])\s+(?:is\s+(?:my\s+)?(?:answer|choice))\b/,
    /\bthe\s+answer\s+is\s+([a-e])\b/,
    /\bi\s+(?:choose|pick|select|want|think)\s+([a-e])\b/,
    /^([a-e])\s*please\b/,
  ];
  for(var i=0;i<pats.length;i++){
    var m=text.match(pats[i]);
    if(m){var l=((m[2]||m[1])+'').toUpperCase();
      if('ABCDE'.indexOf(l)>=0&&Q.choices[l]) return l;}
  }
  // single-word fallback
  var words=text.trim().split(/\s+/);
  if(words.length===1&&/^[a-e]$/.test(words[0])&&Q.choices[words[0].toUpperCase()])
    return words[0].toUpperCase();
  return null;
}
function anyOf(text,list){for(var i=0;i<list.length;i++)if(text.indexOf(list[i])!==-1)return true;return false;}

/* ── Answer handling ─────────────────────────────────────────────────────── */
function handleAnswer(letter){
  setStatus('You said: '+letter); selectRadio(letter);
  if(S.requireConfirm){S.pendingAnswer=letter;showConfirm(letter);}
}
function selectRadio(letter){
  var idx='ABCDE'.indexOf(letter.toUpperCase());if(idx<0)return;
  var sels=['[data-testid="stRadio"] label','[role="radiogroup"] label','.stRadio label'];
  for(var i=0;i<sels.length;i++){
    var labels=doc.querySelectorAll(sels[i]);
    if(labels.length>idx){labels[idx].click();return;}
  }
}
function showConfirm(letter){
  var wrap=$('sf-vep-confirm'),txt=$('sf-vep-confirm-text');
  if(!wrap||!txt)return;
  txt.textContent='You selected '+letter+' \u2014 confirm this answer?';
  wrap.style.display='flex';
  var yes=$('sf-vep-conf-yes');
  if(yes) setTimeout(function(){yes.focus();},50);
  setStatus('Confirm choice '+letter+'?');
}
function confirmAnswer(){
  var wrap=$('sf-vep-confirm');if(wrap)wrap.style.display='none';
  var letter=S.pendingAnswer;S.pendingAnswer=null;if(!letter)return;
  selectRadio(letter);
  clickByText('\u2714 Submit Answer');clickByText('Submit Answer');
  setStatus('Answer '+letter+' confirmed \u2713');setTranscript('\u2713 Confirmed: '+letter);
}
function cancelConfirm(){
  var wrap=$('sf-vep-confirm');if(wrap)wrap.style.display='none';
  S.pendingAnswer=null;
  setStatus('Cancelled \u2014 tap \uD83C\uDF99 to say a new answer');
  setTranscript('Cancelled.\nTap \uD83C\uDF99 and say A, B, C, or D.');
}
function clickByText(fragment){
  var btns=doc.querySelectorAll('button');
  for(var i=0;i<btns.length;i++){
    var t=(btns[i].innerText||btns[i].textContent||'').trim();
    if(t.indexOf(fragment)!==-1){btns[i].click();return true;}
  }
  return false;
}

/* ── UI helpers ──────────────────────────────────────────────────────────── */
function setStatus(t){var el=$('sf-vep-status');if(el)el.textContent=t;}
function setTranscript(t,active){
  if(!S.showTranscript)return;
  var el=$('sf-vep-transcript');if(!el)return;
  el.textContent=t; el.classList.toggle('sf-active',!!active);
}
function updateCtrl(){
  var play=$('sf-vep-play'),pause=$('sf-vep-pause');if(!play)return;
  if(S.speaking&&!S.paused){
    play.disabled=true;if(pause)pause.disabled=false;
  } else {
    play.disabled=false;
    play.innerHTML=S.paused?'\u25B6\u202FResume':'\u25B6';
    play.setAttribute('aria-label',S.paused?'Resume reading':'Play question');
    if(pause)pause.disabled=true;
  }
  updateFab();
}
function updateFab(){
  var fab=$('sf-vep-fab');if(!fab)return;
  fab.classList.remove('sf-playing');
  fab.innerHTML='\u2699';
  fab.setAttribute('aria-label',S.panelOpen?'Close voice settings':'Open voice settings');
  fab.setAttribute('title','Voice settings');
}
function updateProg(){
  var bar=$('sf-vep-pg');if(!bar||!S.fullText||!S.fullText.length)return;
  bar.style.width=Math.min(100,(S.charIdx/S.fullText.length)*100)+'%';
}
function setMicState(on){
  var mic=$('sf-vep-mic'),fab=$('sf-vep-fab');if(!mic)return;
  if(on){mic.classList.add('sf-listening');mic.setAttribute('aria-label','Stop listening');mic.innerHTML='\uD83D\uDD34';}
  else{mic.classList.remove('sf-listening');mic.setAttribute('aria-label','Speak your answer');mic.innerHTML='\uD83C\uDF99';}
  if(fab)fab.classList.toggle('sf-listening',on);
  updateFab();
}
function syncSettings(){
  function cb(id,val){var el=$(id);if(el)el.checked=val;}
  cb('sf-v-autoread',S.autoRead);cb('sf-v-confirm',S.requireConfirm);
  cb('sf-v-transcript',S.showTranscript);cb('sf-v-voice',S.voiceEnabled);
  var sp=$('sf-vep-speed');if(sp)sp.value=String(S.speed);
}
function syncQLabel(){var el=$('sf-vep-qlabel');if(el)el.textContent='Q '+(Q.idx+1)+' / '+Q.total;}
function applyPanelState(){
  var panel=$('sf-vep-panel'),fab=$('sf-vep-fab');if(!panel||!fab)return;
  var collapse=$('sf-vep-collapse');
  panel.classList.toggle('sf-collapsed',!!S.panelCollapsed);
  if(collapse){
    collapse.innerHTML=S.panelCollapsed?'\u25A1':'\u2212';
    collapse.setAttribute('aria-label',S.panelCollapsed?'Expand voice panel':'Collapse voice panel');
    collapse.setAttribute('title',S.panelCollapsed?'Expand voice panel':'Collapse voice panel');
  }
  if(S.panelOpen){panel.classList.add('sf-open');fab.setAttribute('aria-expanded','true');}
  else{panel.classList.remove('sf-open');panel.classList.remove('sf-collapsed');fab.setAttribute('aria-expanded','false');}
  updateFab();
}
function playText(text, openPanel){
  if(!hasTTS){setStatus('TTS not supported in this browser');return;}
  var cleaned=(text||'').replace(/\s+/g,' ').trim();
  if(!cleaned){setStatus('No question text to read');return;}
  if(openPanel!==false){
    S.panelOpen=true; S.panelCollapsed=false;
    applyPanelState(); syncQLabel(); syncSettings();
  }
  S.fullText=cleaned; S.charIdx=0; S._shouldStop=false;
  hardStop(); S._shouldStop=false; speakFrom(0);
}
function togglePanel(){
  if(S.panelOpen&&S.panelCollapsed){S.panelCollapsed=false;}
  else{S.panelOpen=!S.panelOpen;if(!S.panelOpen)S.panelCollapsed=false;}
  applyPanelState();
  if(S.panelOpen){syncQLabel();syncSettings();}
  else{stopSTT();}
}
function isInteractiveTarget(target){
  if(!target)return false;
  if(target.isContentEditable)return true;
  var tag=target.tagName||'';
  if(tag==='SELECT')return true;
  if(tag==='INPUT'||tag==='TEXTAREA')return !target.readOnly&&!target.disabled;
  return tag==='BUTTON'||tag==='A';
}
function handleKeydown(e){
  if((e.code!=='Space'&&e.key!==' ')||e.repeat||e.altKey||e.ctrlKey||e.metaKey||e.shiftKey)return;
  if(isInteractiveTarget(e.target))return;
  e.preventDefault();
  if(S.speaking&&!S.paused){
    hardStop();setStatus('Stopped \u2014 press Space to read again');
  }else{
    playText(buildQuestionOnly(),false);
  }
}
P._sfQuestionAudio={
  playText:function(text, opts){opts=opts||{};playText(text, opts.openPanel);},
  stop:function(){hardStop();},
  isSpeaking:function(){return !!(S.speaking&&!S.paused);}
};

/* ── MutationObserver ────────────────────────────────────────────────────── */
if(P._sfVepObs){try{P._sfVepObs.disconnect();}catch(e){}P._sfVepObs=null;}
if(doc.body){
  P._sfVepObs=new MutationObserver(function(){
    if(S.destroyed) return;
    var nf=!doc.getElementById('sf-vep-fab'),np=!doc.getElementById('sf-vep-panel');
    if(nf)ensureFAB();if(np)ensurePanel();
    if(nf||np){applyPanelState();updateCtrl();setMicState(S.listening);syncSettings();syncQLabel();}
  });
  P._sfVepObs.observe(doc.body,{childList:true,subtree:false});
}
if(P._sfVepKeydown){doc.removeEventListener('keydown',P._sfVepKeydown);}
P._sfVepKeydown=handleKeydown;
doc.addEventListener('keydown',P._sfVepKeydown);

/* ── Question-change handler ─────────────────────────────────────────────── */
function onNewQuestion(){
  hardStop();
  S.currentIdx=Q.idx;S.pendingAnswer=null;S.charIdx=0;S.fullText=buildQuestionOnly();
  var conf=$('sf-vep-confirm');if(conf)conf.style.display='none';
  syncQLabel();updateProg();
  if(S.panelOpen&&!S.panelCollapsed&&S.autoRead&&hasTTS){
    setTimeout(function(){S._shouldStop=false;hardStop();speakQuestion();},420);}
}

/* ── Bootstrap ───────────────────────────────────────────────────────────── */
ensureTTSEngine();
tts=P[TK];
ensureStyles();ensureFAB();ensurePanel();
applyPanelState();updateCtrl();setMicState(S.listening);syncSettings();syncQLabel();
if(S._forceStopOnBoot){S._forceStopOnBoot=false;hardStop();setStatus('Ready');}
if(S.currentIdx!==Q.idx) onNewQuestion();

})();
</script>
"""

# ── Cleanup JS ────────────────────────────────────────────────────────────────

_CLEANUP_JS = """<script>
(function(){
  var P=window.parent;if(!P)return;
  if(P._sfVoiceState){P._sfVoiceState.destroyed=true;}
  if(P._sfVepObs){try{P._sfVepObs.disconnect();}catch(e){}P._sfVepObs=null;}
  if(P._sfVepKeydown){P.document.removeEventListener('keydown',P._sfVepKeydown);P._sfVepKeydown=null;}
  if(P._sfTTSEngine){try{P._sfTTSEngine.stop();}catch(e){}}
  ['sf-vep-fab','sf-vep-panel','sf-vep-style','sf-tts-engine'].forEach(function(id){
    var el=P.document.getElementById(id);if(el)el.remove();
  });
  P._sfQuestionAudio=null;
  P._sfVoiceState=null;P._sfTTSEngine=null;
})();
</script>"""


# ── Public API ────────────────────────────────────────────────────────────────

def render_voice_exam_panel(q: dict, idx: int, total: int) -> None:
    """Inject the Voice Exam Mode panel for an active exam question."""
    data  = build_question_data(q, idx, total)
    qjson = json.dumps(data, ensure_ascii=False)

    # Embed TTS engine and CSS as JS string literals.
    # We use a JS string (not template literal) to hold arbitrary text,
    # which avoids issues with the content containing backticks.
    tts_json  = json.dumps(_TTS_ENGINE_JS)   # JSON-encodes to a safe JS string
    css_json  = json.dumps(_PANEL_CSS)

    bundle = (
        _VOICE_JS
        .replace("__QUESTION_DATA__", qjson)
        .replace("__TTS_ENGINE__",    tts_json)
        .replace("__CSS__",           css_json)
    )

    _components.html(bundle, height=0, scrolling=False)


def cleanup_voice_exam_panel() -> None:
    """Remove the panel and stop all audio. Call when the exam session ends."""
    _components.html(_CLEANUP_JS, height=0, scrolling=False)
