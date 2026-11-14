// Executes the real UI scripts against their real HTML in JavaScriptCore.
// A small DOM adapter checks boot, state rendering and actions without npm.
import Foundation
import JavaScriptCore

let root = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
let adapter = """
var window = this;
var navigator = {userAgent:'Macintosh'};
var requests = [], timers = [], stateRequests = [];
function setTimeout(f) { timers.push(f); return timers.length; }
function clearTimeout() {}
function setInterval() { return 1; }
function clearInterval() {}
var URL = {createObjectURL:function(){return 'blob:fixture';},revokeObjectURL:function(){}};
function Node(tag) {
 this.tagName=tag.toUpperCase(); this.children=[]; this.attrs={}; this.dataset={};
 this.className=''; this.hidden=false; this.disabled=false; this.style={}; this.handlers={}; this._text='';
 this.scrollTop=0; this.scrollHeight=0; this.clientHeight=0;
 var self=this;
 this.classList={add:function(c){this.toggle(c,true);},remove:function(c){this.toggle(c,false);},toggle:function(c,on){
  var a=self.className.split(/\\s+/).filter(Boolean), i=a.indexOf(c);
  if(on===undefined)on=i<0; if(on&&i<0)a.push(c); if(!on&&i>=0)a.splice(i,1);self.className=a.join(' ');
 }};
}
Object.defineProperty(Node.prototype,'textContent',{get:function(){return this._text+this.children.map(function(n){return n.textContent;}).join('');},set:function(t){this._text=String(t);this.children=[];}});
Object.defineProperty(Node.prototype,'firstElementChild',{get:function(){return this.children[0];}});
Node.prototype.setAttribute=function(k,v){this.attrs[k]=String(v);if(k==='class')this.className=v;if(k==='hidden')this.hidden=true;if(k==='disabled')this.disabled=true;if(k.indexOf('data-')===0)this.dataset[k.slice(5).replace(/-([a-z])/g,function(_,c){return c.toUpperCase();})]=v;};
Node.prototype.getAttribute=function(k){return this.attrs[k]===undefined?null:this.attrs[k];};
Node.prototype.hasAttribute=function(k){return this.attrs[k]!==undefined;};
Node.prototype.removeAttribute=function(k){delete this.attrs[k];if(k==='hidden')this.hidden=false;};
Node.prototype.appendChild=function(n){return this.insertBefore(n,null);};
Node.prototype.insertBefore=function(n,at){if(n.tagName==='#FRAGMENT'){n.children.slice().forEach(this.appendChild.bind(this));return n;}if(n.parentNode)n.parentNode.removeChild(n);var i=at?this.children.indexOf(at):-1;if(i<0)i=this.children.length;this.children.splice(i,0,n);n.parentNode=this;return n;};
Node.prototype.removeChild=function(n){var i=this.children.indexOf(n);if(i>=0)this.children.splice(i,1);n.parentNode=null;};
Node.prototype.replaceChildren=function(n){this.children=[];this._text='';if(n)this.appendChild(n);};
Node.prototype.addEventListener=function(k,f){(this.handlers[k]||(this.handlers[k]=[])).push(f);};
Node.prototype.emit=function(k,e){var self=this;(this.handlers[k]||[]).forEach(function(f){f.call(self,e||{});});};
Node.prototype.focus=function(){document.activeElement=this;};Node.prototype.click=function(){this.emit("click",{target:this,preventDefault:function(){}});};
Node.prototype.contains=function(n){return n===this||!!(n&&n.parentNode&&this.contains(n.parentNode));};
Node.prototype.getBoundingClientRect=function(){return {right:300,bottom:100};};
Node.prototype.showModal=function(){this.open=true;};Node.prototype.close=function(){this.open=false;};
Node.prototype.matches=function(s){if(s[0]==='#')return this.attrs.id===s.slice(1);if(s[0]==='.')return this.className.split(/\\s+/).indexOf(s.slice(1))>=0;var m=s.match(/^(\\w+)?\\[([^\\]]+)\\]$/);if(m)return (!m[1]||this.tagName===m[1].toUpperCase())&&this.hasAttribute(m[2]);return this.tagName===s.toUpperCase();};
Node.prototype.querySelectorAll=function(s){var out=[];this.children.forEach(function(n){if(n.matches(s))out.push(n);out=out.concat(n.querySelectorAll(s));});return out;};
Node.prototype.querySelector=function(s){return this.querySelectorAll(s)[0]||null;};
Node.prototype.closest=function(s){return this.matches(s)?this:this.parentNode?this.parentNode.closest(s):null;};
var document=new Node('#document');
document.getElementById=function(id){return this.querySelector('#'+id);};
document.readyState='complete';document.visibilityState='visible';
document.createElement=function(t){return new Node(t);};document.createElementNS=function(_,t){return new Node(t);};document.createDocumentFragment=function(){return new Node('#fragment');};
var stack=[document];
__html.match(/<!--[\\s\\S]*?-->|<[^>]+>|[^<]+/g).forEach(function(token){
 if(token.indexOf('<!--')===0||token.indexOf('<!')===0)return;
 if(token.indexOf('</')===0){if(stack.length>1)stack.pop();return;}
 if(token[0]!=='<'){stack[stack.length-1]._text+=token;return;}
 var m=token.match(/^<([\\w-]+)/);if(!m)return;var n=new Node(m[1]);
 var attrs=token.slice(m[0].length).match(/([\\w-]+)(?:=(?:"[^"]*"|'[^']*'|[^\\s>]+))?/g)||[];
 attrs.forEach(function(a){var p=a.match(/^([\\w-]+)(?:=(.*))?$/);if(!p)return;var v=p[2]||'';if(v[0]==='"'||v[0]==="'")v=v.slice(1,-1);n.setAttribute(p[1],v);});
 stack[stack.length-1].appendChild(n);if(!/^(meta|link|img|input|br|hr|use)$/i.test(m[1])&&!token.endsWith('/>'))stack.push(n);
});
document.documentElement=document.querySelector('html');
window.addEventListener=function(){};window.innerWidth=1040;window.innerHeight=720;
window.location={pathname:'/s/fixture/'};
window.__FTE_TOKEN__='fixture';window.__FTE_BASE__='/s/fixture';
function EventSource(){this.readyState=1;}EventSource.prototype.addEventListener=function(){};EventSource.prototype.close=function(){};
function fetch(path,opts){requests.push({path:path,opts:opts});if(typeof __deferState!=='undefined'&&__deferState&&path==='/api/state')return new Promise(function(resolve,reject){stateRequests.push({resolve:resolve,reject:reject});});return Promise.resolve({ok:true,status:200,json:function(){return Promise.resolve(path.indexOf('/manifest')>=0?__manifest:path.indexOf('/api/access')>=0?__access:path==='/api/state'?__state:{ok:true});},blob:function(){return Promise.resolve({});}});}
function assert(ok,message){if(!ok)throw Error(message);}
function byId(id){return document.querySelector('#'+id);}
"""

let item: [String: Any] = ["id":"one", "kind":"file", "name":"informe con ñ <script>.txt", "size":36, "sizeText":"36 B", "ext":"txt", "path":"/tmp/fixture.txt"]
let manifest: [String: Any] = ["files":[["id":"one","name":"informe con ñ <script>.txt","size":36,"sizeText":"36 B","ext":"txt"]],"folders":[],"totals":["files":1,"bytesText":"36 B"]]
var failure: String?
func run(_ directory: String, _ status: String, _ checks: String) throws {
 guard let ctx = JSContext() else { fatalError("JavaScriptCore unavailable") }
 ctx.exceptionHandler = { _, value in failure = value?.toString() }
 ctx.setObject(try String(contentsOf: root.appendingPathComponent("\(directory)/index.html"), encoding:.utf8), forKeyedSubscript:"__html" as NSString)
 let state: [String: Any] = ["items":(status == "empty" || status == "receiving" || status == "error-empty") ? [] : [item],"totals":["items":1,"files":1,"bytesText":"36 B"],"share":["status":status == "empty" ? "idle" : status == "receiving" ? "live" : status == "error-empty" ? "error" : status,"url":(status == "live" || status == "receiving") ? "https://fixture.trycloudflare.com/s/token" : "","lanUrl":status == "error" ? "http://192.0.2.1/s/token" : "","error":(status == "error" || status == "error-empty") ? "fixture failure" : ""],"visitors":[],"transfers":[],"stats":[:],"log":[],"settings":["theme":"light","uploadsEnabled":status == "receiving","maxUploadMB":100,"uploadDir":"/tmp/fixture-uploads","pageTitle":"Archivos compartidos","pagePasswordSet":false],"history":[["id":"history-one","ip":"192.0.2.24","name":"Ana","label":"Chrome · Windows","visits":2,"downloads":1,"bytesText":"36 B","blocked":false]],"requests":status == "request" ? [["id":"request-one","ip":"192.0.2.24","name":"Ana","status":"pending"]] : []]
 ctx.setObject(state, forKeyedSubscript:"__state" as NSString)
 var scenarioManifest = manifest
 if status == "file-owner" { scenarioManifest["files"] = [["id":"one","name":"privado.txt","folder":"Documentos","protectionName":"privado.txt","protectionKind":"file","size":36,"sizeText":"36 B","ext":"txt","locked":true,"protected":true]] }
 if status == "locked" { scenarioManifest["files"] = [["id":"one","name":"privado.txt","size":36,"sizeText":"36 B","ext":"txt","locked":true,"protected":true]] }
 ctx.setObject(scenarioManifest, forKeyedSubscript:"__manifest" as NSString)
 ctx.setObject(["status":status == "password" ? "password" : status == "pending" ? "pending" : "allowed","theme":"light","uploadsEnabled":false], forKeyedSubscript:"__access" as NSString)
 ctx.setObject(status == "settings-loading" || status == "settings-failure", forKeyedSubscript:"__deferState" as NSString)
 ctx.evaluateScript(adapter)
 if failure == nil { ctx.evaluateScript(try String(contentsOf:root.appendingPathComponent("\(directory)/app.js"),encoding:.utf8)) }
 if failure == nil { ctx.evaluateScript(checks) }
 if failure == nil { ctx.evaluateScript("if(typeof __afterJobs === 'function') __afterJobs();") }
 if let error = failure { fputs("FAIL \(directory)/\(status): \(error)\n",stderr);exit(1) }
 print("PASS \(directory)/\(status)")
}
try run("frontend","empty","""
assert(!byId('view-empty').hidden,'empty state did not boot');
assert(byId('view-active').hidden,'active view flashed on empty boot');
assert(byId('btn-copy').disabled,'copy enabled before readiness');
var prevented=false; document.emit('keydown',{key:'o',metaKey:true,preventDefault:function(){prevented=true;}});
assert(prevented&&requests.some(function(r){return r.path==='/api/items/add-files';}),'file shortcut not wired');
""")
try run("frontend","starting","""
assert(!byId('view-active').hidden,'active state not rendered');
assert(byId('btn-copy').disabled,'unverified link can be copied');
assert(byId('btn-share-toggle').querySelector('.btn-label').textContent==='Cancelar','preparing action is not Cancel');
byId('btn-share-toggle').emit('click');
assert(requests.some(function(r){return r.path==='/api/share/stop';}),'cancel not wired');
""")
try run("frontend","live","""
assert(!byId('btn-copy').disabled,'ready link cannot be copied');
assert(byId('url-hint').hidden,'placeholder still visible on ready link');
assert(!byId('btn-open').disabled&&!byId('btn-preview').disabled,'open controls disabled while live');
assert(byId('items-list').children.length===1,'shared file not rendered');
byId('btn-open').emit('click');byId('btn-preview').emit('click');byId('btn-copy').emit('click');
assert(requests.filter(function(r){return r.path==='/api/share/open';}).length===2,'open/preview not wired');
assert(requests.some(function(r){return r.path==='/api/share/copy';}),'copy not wired');
""")
try run("frontend","error","""
assert(!byId('share-error').hidden,'error is invisible');
assert(!byId('link-foot').hidden&&!byId('lan-line').hidden,'LAN fallback invisible');
assert(byId('btn-copy').disabled,'unverified public copy enabled');
byId('btn-retry').emit('click');assert(requests.some(function(r){return r.path==='/api/share/start';}),'retry not wired');
""")
try run("public","live","""
assert(byId('stage').getAttribute('aria-busy')==='false','public page did not finish loading');
assert(!byId('cta').hidden,'ZIP action hidden');
assert(byId('zipLink').href==='/s/fixture/zip','ZIP URL incorrect');
var dl=byId('stage').querySelector('a[data-dl]');assert(dl&&dl.href==='/s/fixture/download/one','individual download URL incorrect');
assert(byId('stage').textContent.indexOf('informe con ñ <script>.txt')>=0,'Unicode filename lost');
""")


try run("frontend","live","""
byId('btn-settings').emit('click');
assert(byId('settings-dialog').open,'settings modal did not open');
assert(byId('setting-theme').value==='light','theme default is not light');
byId('setting-theme').value='dark';
byId('settings-form').emit('submit',{preventDefault:function(){}});
var patch=JSON.parse(requests.filter(function(r){return r.path==='/api/settings';}).pop().opts.body);
assert(patch.theme==='dark','theme setting was not sent');
assert(!Object.prototype.hasOwnProperty.call(patch,'pagePassword'),'unchanged password was overwritten');
var row=byId('items-list').children[0],prevented=false;
row.emit('contextmenu',{clientX:100,clientY:100,preventDefault:function(){prevented=true;}});
assert(prevented&&!byId('item-menu').hidden,'file context menu did not open');
var protect=byId('item-menu').querySelectorAll('button')[1];protect.emit('click');
assert(byId('edit-dialog').open,'password dialog did not open');
byId('edit-input').value='contraseña de prueba';byId('edit-form').emit('submit',{preventDefault:function(){}});
var pw=JSON.parse(requests.filter(function(r){return r.path==='/api/items/password';}).pop().opts.body);
assert(pw.id==='one'&&pw.password==='contraseña de prueba','item password request incorrect');
""")
try run("frontend","receiving","""
assert(!byId('view-active').hidden,'receiving-only link was hidden');
assert(!byId('btn-copy').disabled,'receiving-only link cannot be copied');
assert(!byId('items-none').hidden,'receiving-only empty file list lacks explanation');
""")
try run("public","password","""
assert(byId('cta').hidden,'download ZIP exposed before authentication');
assert(byId('stage').textContent.indexOf('Acceso con contraseña')>=0,'password gate missing');
assert(!requests.some(function(r){return r.path.indexOf('/api/manifest')>=0;}),'manifest requested before authorization');
""")
try run("public","pending","""
assert(byId('stage').textContent.indexOf('Esperando autorización')>=0,'pending request view missing');
assert(byId('cta').hidden,'downloads exposed while approval pending');
""")
try run("public","locked","""
assert(byId('cta').hidden,'ZIP enabled with all files locked');
var unlock=byId('stage').querySelector('.unlock-button');assert(unlock,'locked file lacks unlock action');
unlock.emit('click');assert(byId('unlock-dialog').open,'unlock modal did not open');
byId('unlock-password').value='clave';byId('unlock-form').emit('submit',{preventDefault:function(){}});
var req=requests.filter(function(r){return r.path.indexOf('/api/unlock')>=0;}).pop();assert(req&&JSON.parse(req.opts.body).id==='one','unlock request incorrect');
""")

try run("frontend","error-empty","""
assert(!byId('view-active').hidden,'startup error hidden when no files');
assert(!byId('share-error').hidden&&byId('share-error-text').textContent==='fixture failure','specific startup error missing');
""")
try run("frontend","request","""
assert(!byId('request-panel').hidden,'pending requests panel hidden');
byId('request-list').querySelectorAll('button')[1].emit('click');
var decision=JSON.parse(requests.filter(function(r){return r.path==='/api/requests/respond';}).pop().opts.body);
assert(decision.id==='request-one'&&decision.accept===true,'approval request body incorrect');
""")
try run("frontend","live","""
byId('btn-settings').emit('click');byId('tab-history').emit('click');
assert(!byId('settings-history').hidden,'history tab did not activate');
assert(byId('history-list').textContent.indexOf('Ana')>=0,'saved visitor name missing');
byId('history-list').querySelectorAll('button')[0].emit('click');
byId('edit-input').value='Ana oficina';byId('edit-form').emit('submit',{preventDefault:function(){}});
var rename=JSON.parse(requests.filter(function(r){return r.path==='/api/visitors/name';}).pop().opts.body);
assert(rename.ip==='192.0.2.24'&&rename.name==='Ana oficina','history rename request incorrect');
""")

try run("frontend","settings-loading","""
assert(stateRequests.length===1,'initial state request was not deferred');
byId('btn-settings').emit('click');
assert(!byId('settings-dialog').open,'settings opened before its snapshot arrived');
assert(byId('btn-settings').disabled,'settings opener did not mark its pending request');
assert(stateRequests.length===2,'settings opener did not request a complete snapshot');
stateRequests[1].resolve({ok:true,status:200,json:function(){return Promise.resolve(__state);}});
function __afterJobs(){
 assert(byId('settings-dialog').open,'settings did not open after the snapshot arrived');
 assert(byId('setting-upload-dir').value===__state.settings.uploadDir,'settings opened with an invented empty upload directory');
 assert(byId('setting-title').value===__state.settings.pageTitle,'settings title was lost during startup');
 assert(!byId('btn-settings').disabled,'settings opener remained disabled after success');
}
""")
try run("frontend","settings-failure","""
byId('btn-settings').emit('click');
stateRequests[1].reject(new Error('HTTP 503'));
function __afterJobs(){
 assert(!byId('settings-dialog').open,'settings opened with missing backend data after an error');
 assert(!byId('btn-settings').disabled,'settings opener cannot be retried after failure');
 assert(byId('toasts').textContent.indexOf('HTTP 503')>=0,'settings opener hid the specific failure reason');
 assert(stateRequests.length===2,'settings opener retried recursively');
}
""")

try run("public","file-owner","""
var unlock=byId('stage').querySelector('.unlock-button');assert(unlock,'grouped protected file lacks unlock action');
unlock.emit('click');
assert(byId('unlock-title').textContent==='Desbloquear archivo','folder grouping incorrectly labeled a file password as a folder password');
assert(byId('unlock-name').textContent==='privado.txt','unlock dialog did not use the effective protection owner name');
""")

func luminance(_ hex: String) -> Double {
 var h = String(hex.dropFirst())
 if h.count == 3 { h = h.map { "\($0)\($0)" }.joined() }
 let v = UInt32(h, radix:16)!
 let channels = [Double((v >> 16) & 255),Double((v >> 8) & 255),Double(v & 255)].map { c -> Double in
  let n = c/255; return n <= 0.04045 ? n/12.92 : pow((n+0.055)/1.055,2.4)
 }
 return channels[0]*0.2126 + channels[1]*0.7152 + channels[2]*0.0722
}
for directory in ["frontend","public"] {
 let filename = directory == "frontend" ? "app.css" : "style.css"
 let css = try String(contentsOf:root.appendingPathComponent("\(directory)/\(filename)"),encoding:.utf8)
 let roots = try NSRegularExpression(pattern:"(?::root|html\\[data-theme=\"dark\"\\])\\s*\\{([^}]*)\\}")
 let tokens = try NSRegularExpression(pattern:"--([\\w-]+):\\s*(#[0-9a-fA-F]+)")
 for palette in roots.matches(in:css,range:NSRange(css.startIndex...,in:css)) {
  let body = String(css[Range(palette.range(at:1),in:css)!])
  var colors: [String:String] = [:]
  for token in tokens.matches(in:body,range:NSRange(body.startIndex...,in:body)) {
   colors[String(body[Range(token.range(at:1),in:body)!])] = String(body[Range(token.range(at:2),in:body)!])
  }
  for (fg,bg) in [("ink","bg"),("ink-soft","bg-elev"),("ink-faint","bg"),("accent-ink","accent")] {
   let a=luminance(colors[fg]!), b=luminance(colors[bg]!)
   let ratio=(max(a,b)+0.05)/(min(a,b)+0.05)
   if ratio < 4.5 { fputs("FAIL \(directory) contrast \(fg)/\(bg): \(ratio)\n",stderr);exit(1) }
  }
 }
 print("PASS \(directory) light/dark text contrast")
}
