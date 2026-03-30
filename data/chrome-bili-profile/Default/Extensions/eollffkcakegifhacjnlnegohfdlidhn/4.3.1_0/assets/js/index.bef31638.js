import"./runtime.b9df0329.js";import{C as E,L as l,u as U}from"./use-chrome-storage.ee6d2686.js";import{j as d,R as N}from"./jsx-runtime.c01305c6.js";import{u as _}from"./react-hotkeys-hook.esm.57e01376.js";import{r as c}from"./index.221108e0.js";import{g as m}from"./ga-track-event.c7cbcd22.js";const k="vc-root",j=".relative.flex-1.flex.items-center.gap-2.shrink.min-w-0",R='fieldset [contenteditable="true"]',q="/assets/png/imgClaude-mic.chunk.png",H="/assets/svg/imgClaude-stop.chunk.svg";function $(){const{chromeStorage:t}=c.exports.useContext(E),[i,u]=c.exports.useState(!1),[a,h]=c.exports.useState(!1),[w,x]=c.exports.useState(0),s=c.exports.useRef(null),p=c.exports.useRef(a),C=c.exports.useRef(window.location.href);c.exports.useEffect(()=>{p.current=a},[a]),c.exports.useEffect(()=>{setTimeout(()=>{u(!0)},500)},[]),c.exports.useEffect(()=>{var I;if(!t)return;const o=window.SpeechRecognition||window.webkitSpeechRecognition;s.current=new o,s.current.continuous=!0,s.current.interimResults=!0,s.current.lang=(I=t.claudeLanguage)!=null?I:"en-US";const f=e=>{const n=document.querySelector(R);if(n){const r=window.getSelection();if(r&&r.rangeCount>0){const g=r.getRangeAt(0);g.deleteContents();const b=document.createTextNode(e);g.insertNode(b),g.setStartAfter(b),g.setEndAfter(b),r.removeAllRanges(),r.addRange(g)}else n.textContent+=e;n.focus()}};s.current.onresult=e=>{for(let n=e.resultIndex;n<e.results.length;++n)if(e.results[n].isFinal){if(p.current){const r=e.results[n][0].transcript;f(r),x(0)}}else x(r=>r+1)},s.current.onend=()=>{h(!1)},s.current.onerror=e=>{var n,r;l.error("Speech recognition error: "+e.error),m({name:`claude_error_${(n=e==null?void 0:e.error)==null?void 0:n.replace(/-/g,"_")}`}),e.error==="language-not-supported"?alert("Error: Speech recognition is not support in this browser. Please use Google Chrome."):e.error==="not-allowed"?alert("Error: Microphone access denied."):e.error==="network"&&alert("Error: Unable to contact the speech recognition server."),h(!1),(r=s.current)==null||r.stop()}},[t]);const y=()=>{var o;l.info("Stop recording"),m({name:"claude_stop_recording"}),(o=s.current)==null||o.stop()},T=()=>{clearInterval(window==null?void 0:window.generatorSearchInterval),window.generatorSearchInterval=setInterval(()=>{const o=window.location.href;o!==C.current&&(C.current=o,l.warn("URL changed"),y())},1e3)},L=()=>{var f;l.success("Start recording"),m({name:"claude_start_recording"}),(f=s.current)==null||f.start();const o=document.querySelector(R);o==null||o.focus(),T()},v=()=>{p.current?y():L(),h(!p.current)};return _("ctrl+r",()=>{l.info("Toggle recording"),m({name:"claude_shortcut_start_recording"}),v()},{enableOnContentEditable:!0}),t.enableClaude?d("div",{style:{},className:` fade-in-element  transition-opacity duration-1000 ${i?"opacity-100":"opacity-0"}`,children:d("button",{title:"Toggle recording (Ctrl + R)","aria-label":"Toggle recording","data-state":"closed",className:`
                ${a?"":"vc-record-button--idle"}
              
                rounded-lg 
                border-0.5 border-border-300
                h-8 min-w-8
                inline-flex
                items-center
                justify-center
                relative
                shrink-0
                ring-offset-2
                ring-offset-bg-300
                ring-accent-main-100
                focus-visible:outline-none
                focus-visible:ring-1
                disabled:pointer-events-none
                disabled:opacity-50
                disabled:shadow-none
                disabled:drop-shadow-none text-text-200
                        transition-all
                        font-styrene
                        active:bg-bg-400
                        hover:bg-bg-500/40
                        hover:text-text-100 rounded-md active:scale-95 !rounded-lg`,onClick:()=>v(),style:{width:32,height:32,cursor:"pointer",transition:"background-color 1s ease",backgroundColor:a?w===0?"#f0b8b8":"#c9f0b8":""},children:d("img",{style:{width:16,marginLeft:"auto",marginRight:"auto",borderRadius:5,transform:`rotate(${w*50}deg)`,transition:"transform 0.5s ease"},src:chrome.runtime.getURL(a?H:q),alt:"microphone"})})}):null}function M(){const t=U();return _("ctrl+shift+l",()=>{const i=window.localStorage.getItem("vc-log")==="true";window.localStorage.setItem("vc-log",i?"false":"true"),console.log("toggle vc-log on:",!i)}),d(E.Provider,{value:t,children:d($,{})})}l.setup();l.info("Claude: Content Script Loaded");let S=500;const O=3e3,A=()=>{l.info("VC: Searching for input toolbar");const t=document.querySelector(j),i=document.getElementById(k);if(t&&!i){const u=document.createElement("div");u.classList.add("vc-extension"),t.id=k,t.prepend(u),N.render(d(M,{}),u),l.info("VC: App rendered");const a=document.querySelector(R);a&&(a.style.paddingRight="20px")}S=Math.min(S+500,O),setTimeout(A,S)};setTimeout(A,0);function B(t){const i=document.createElement("style");i.textContent=t,document.head.append(i)}const D=`
  [data-mode="dark"] .vc-record-button--idle {
     filter: invert(100%); 
  }
`;B(D);
