# -*- coding: utf-8 -*-
"""把 manifest.json 渲染成单文件离线图库 gallery.html。

设计要点:
- 单文件、零依赖、可 file:// 直接打开:数据内嵌,图片按相对路径引用。
- 「图录」气质:立绘用 Mincho 字体呈现角色名,资源 id / 尺寸用等宽字体,作为作品的编目号。
- 三种视图:
  * 素材 —— 立绘/cut-in/背景/剧情图/图标,分类**开关**可多选,另有「仅角色相关」筛选;
  * 剧情 —— 按角色聚合(个人剧情/角色剧情/酒馆剧情/支线/序章),条目数完全取自数据;
  * 动态 —— Live2D 模型(moc3+动作+纹理)与 Spine 骨架,影片只登记状态。
- 签名交互:立绘详情里按游戏原生分层叠加「表情差分」(坐标来自预制体布局),点击即可切换。

数据瘦身:图库内嵌的是裁剪后的 manifest(motions 只留名字、动态只留 png 文件),
避免单文件体积随动态素材数量爆炸;完整信息仍在 output/manifest.json。
"""
from __future__ import annotations

import json
from pathlib import Path

TEMPLATE = r"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ドットアビスX CG図録</title>
<style>
:root{
  --void:#070a11; --slate:#0e1521; --slate2:#0b111b;
  --mist:#93a4bd; --bone:#e7ecf4; --seal:#cf5b4c;
  --line:rgba(231,236,244,.10); --line2:rgba(231,236,244,.18);
  --mincho:"Yu Mincho",YuMincho,"Hiragino Mincho ProN","Noto Serif JP",serif;
  --ui:"Yu Gothic UI","Yu Gothic","Hiragino Kaku Gothic ProN","Noto Sans JP",system-ui,sans-serif;
  --mono:"Cascadia Mono",Consolas,"SF Mono",monospace;
}
*{box-sizing:border-box}
html,body{margin:0}
body{
  background:
    radial-gradient(circle at 12% -10%, rgba(111,151,196,.10), transparent 55%),
    radial-gradient(rgba(231,236,244,.055) 1px, transparent 1px) 0 0/22px 22px,
    linear-gradient(180deg,#080c14,#070a11 60%,#050810);
  color:var(--bone); font-family:var(--ui); font-size:14px; line-height:1.6;
  -webkit-font-smoothing:antialiased;
}
a{color:inherit}
/* ── 顶栏 ─────────────────────────────── */
.top{
  position:sticky; top:0; z-index:20; display:flex; align-items:baseline; gap:16px;
  padding:16px 24px 14px; border-bottom:1px solid var(--line);
  background:linear-gradient(180deg,rgba(7,10,17,.96),rgba(7,10,17,.86));
  backdrop-filter:blur(8px);
}
.top h1{font-family:var(--mincho); font-size:19px; font-weight:600; letter-spacing:.06em; margin:0; white-space:nowrap}
.top h1 .seal{color:var(--seal); font-size:12px; vertical-align:.25em; margin-right:8px}
.top h1 em{font-style:normal; color:var(--mist); font-size:14px; letter-spacing:.18em; margin-left:10px}
.top .stat{margin-left:auto; font-family:var(--mono); font-size:11px; color:var(--mist); letter-spacing:.04em}
/* ── 布局 ─────────────────────────────── */
.wrap{display:grid; grid-template-columns:228px minmax(0,1fr); gap:0; align-items:start}
.rail{
  position:sticky; top:57px; height:calc(100vh - 57px); overflow:auto;
  padding:18px 14px 32px 24px; border-right:1px solid var(--line);
}
.rail h2{font-size:11px; letter-spacing:.22em; color:var(--mist); font-weight:600; margin:0 0 10px; display:flex; gap:8px; align-items:baseline}
.rail h2 small{font-size:10px; letter-spacing:.08em; color:rgba(147,164,189,.7); font-weight:400}
.rail section+section{margin-top:0}
.rail section[hidden]{display:none}
.modes{display:grid; grid-template-columns:repeat(3,1fr); gap:4px; margin-bottom:20px}
.modes button{
  padding:7px 4px; background:var(--slate2); border:1px solid var(--line2); color:var(--mist);
  font:inherit; font-size:12.5px; cursor:pointer; border-radius:2px;
}
.modes button[aria-pressed="true"]{background:rgba(207,91,76,.12); border-color:var(--seal); color:var(--bone)}
.toggles{display:flex; flex-wrap:wrap; gap:5px; margin-bottom:18px}
.toggles button{
  display:flex; gap:7px; align-items:baseline; padding:5px 9px; background:none;
  border:1px solid var(--line2); color:var(--mist); font:inherit; font-size:12px;
  cursor:pointer; border-radius:2px;
}
.toggles button:hover{color:var(--bone)}
.toggles button[aria-pressed="true"]{border-color:var(--seal); background:rgba(207,91,76,.10); color:var(--bone)}
.toggles button .n{font-family:var(--mono); font-size:10.5px; opacity:.75}
.switch{display:flex; gap:8px; align-items:center; margin:0 0 18px; font-size:12.5px; color:var(--mist); cursor:pointer}
.switch input{accent-color:var(--seal)}
.search input{
  width:100%; padding:7px 9px; color:var(--bone); font:inherit; font-size:13px;
  background:var(--slate2); border:1px solid var(--line2); border-radius:2px;
}
.search input::placeholder{color:var(--mist)}
.search input:focus-visible{outline:2px solid var(--seal); outline-offset:1px}
.chars{display:flex; flex-direction:column; gap:1px; margin-top:6px}
.chars button{
  display:flex; gap:8px; padding:4px 9px; background:none; border:0; color:var(--mist);
  font:inherit; font-size:12.5px; cursor:pointer; text-align:left; border-radius:2px;
}
.chars button:hover{color:var(--bone); background:rgba(231,236,244,.05)}
.chars button[aria-pressed="true"]{color:var(--seal)}
.chars button span{margin-left:auto; font-family:var(--mono); font-size:10.5px; opacity:.7}
.note{color:var(--mist); font-size:11.5px; line-height:1.7; margin:0 0 14px}
/* ── 网格 ─────────────────────────────── */
main{padding:22px 24px 64px; min-width:0}
.modehead{display:flex; align-items:baseline; gap:12px; margin:0 0 16px}
.modehead h2{font-family:var(--mincho); font-size:17px; font-weight:600; margin:0; letter-spacing:.04em}
.modehead p{margin:0; color:var(--mist); font-size:12px}
.grid{display:grid; gap:20px 16px; grid-template-columns:repeat(auto-fill,minmax(216px,1fr))}
.grid.compact{grid-template-columns:repeat(auto-fill,minmax(112px,1fr)); gap:14px 12px}
.card{
  display:flex; flex-direction:column; padding:0; text-align:left; cursor:pointer;
  background:linear-gradient(180deg,var(--slate),var(--slate2));
  border:1px solid var(--line); border-radius:2px; color:var(--bone); font:inherit;
  transition:transform .16s ease, border-color .16s ease;
}
.card:hover{transform:translateY(-2px); border-color:var(--line2)}
.card:focus-visible{outline:2px solid var(--seal); outline-offset:2px}
.thumb{display:grid; place-items:center; padding:10px; aspect-ratio:4/3; overflow:hidden}
.grid.compact .thumb{aspect-ratio:1/1; padding:6px}
.thumb img{max-width:100%; max-height:100%; object-fit:contain; image-rendering:auto}
.thumb .glyph{
  font-family:var(--mono); font-size:22px; color:rgba(147,164,189,.55); letter-spacing:.1em;
  border:1px dashed var(--line2); padding:12px 14px; border-radius:2px; text-align:center;
}
.thumb .glyph small{display:block; font-size:10px; letter-spacing:.06em; margin-top:6px}
.cap{padding:9px 11px 10px; border-top:1px solid var(--line)}
.cap b{display:block; font-family:var(--mincho); font-weight:600; font-size:14.5px; letter-spacing:.02em}
.cap i{display:block; font-style:normal; color:var(--mist); font-size:11.5px; margin-top:1px;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.cap u{display:block; text-decoration:none; font-family:var(--mono); font-size:10.5px; color:var(--mist); margin-top:5px; opacity:.85}
.badges{display:flex; gap:5px; flex-wrap:wrap; margin-top:6px}
.badge{
  font-family:var(--mono); font-size:10px; letter-spacing:.04em; color:var(--mist);
  border:1px solid var(--line2); padding:1px 6px; border-radius:2px;
}
.badge.r18{color:#e2a0a0; border-color:rgba(207,91,76,.5)}
.badge.on{color:var(--bone); border-color:rgba(231,236,244,.4)}
.empty{color:var(--mist); padding:40px 4px; font-size:13.5px}
/* ── 剧情列表 ─────────────────────────── */
.sections{display:flex; flex-direction:column; gap:26px}
.sect h3{font-size:12px; letter-spacing:.2em; color:var(--mist); font-weight:600; margin:0 0 10px;
  display:flex; gap:10px; align-items:baseline}
.sect h3 .n{font-family:var(--mono); font-size:11px; color:var(--seal); letter-spacing:.04em}
.rowlist{display:flex; flex-direction:column; gap:6px}
.row{
  display:grid; grid-template-columns:auto minmax(0,1fr) auto; gap:12px; align-items:center;
  padding:9px 12px; background:linear-gradient(180deg,var(--slate),var(--slate2));
  border:1px solid var(--line); border-radius:2px; cursor:pointer; color:var(--bone);
  font:inherit; text-align:left;
}
.row:hover{border-color:var(--line2)}
.row .no{font-family:var(--mono); font-size:11px; color:var(--mist); min-width:3.2em}
.row b{font-family:var(--mincho); font-weight:600; font-size:14px}
.row i{font-style:normal; color:var(--mist); font-size:11.5px; display:block;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.row .counts{display:flex; gap:6px; flex-wrap:wrap; justify-content:flex-end}
/* ── 详情 ─────────────────────────────── */
.viewer{position:fixed; inset:0; z-index:60; display:grid; grid-template-columns:minmax(0,1fr) 360px;
  background:rgba(4,7,12,.95); backdrop-filter:blur(3px)}
.viewer[hidden]{display:none}
.stage{overflow:auto; display:grid; place-items:center; padding:28px}
.stage.zoom{place-items:start}
.frame{position:relative; max-width:100%; max-height:100%; line-height:0}
.frame>img{max-width:100%; max-height:calc(100vh - 56px); width:auto; height:auto}
.frame .face{position:absolute; pointer-events:none}
.stage.zoom .frame>img{max-width:none; max-height:none}
.placeholder{
  font-family:var(--mono); color:var(--mist); font-size:13px; text-align:center;
  border:1px dashed var(--line2); padding:40px 34px; line-height:2;
}
.info{border-left:1px solid var(--line); padding:26px 22px 40px; overflow:auto; background:rgba(7,10,17,.92)}
.info .kicker{font-family:var(--mono); font-size:11px; color:var(--seal); letter-spacing:.16em}
.info h3{font-family:var(--mincho); font-size:23px; font-weight:600; margin:8px 0 2px; letter-spacing:.03em}
.info .sub{color:var(--mist); font-size:13px}
.info .title{color:var(--seal); font-size:12px; margin-top:6px; letter-spacing:.06em}
.info .desc{color:var(--mist); font-size:12.5px; margin:14px 0 0; white-space:pre-line; cursor:pointer;
  display:-webkit-box; -webkit-line-clamp:6; -webkit-box-orient:vertical; overflow:hidden}
.info .desc.open{display:block}
.faces{margin-top:20px}
.faces h4{font-size:11px; letter-spacing:.2em; color:var(--mist); font-weight:600; margin:0 0 8px}
.faces .row{display:flex; flex-wrap:wrap; gap:4px; padding:0; background:none; border:0; cursor:default}
.faces button{padding:4px 9px; font:inherit; font-size:12px; color:var(--bone); cursor:pointer;
  background:var(--slate); border:1px solid var(--line2); border-radius:2px}
.faces button[aria-pressed="true"]{border-color:var(--seal); color:var(--seal)}
dl.facts{margin:22px 0 0; display:grid; grid-template-columns:auto minmax(0,1fr); gap:6px 12px; font-size:12px}
dl.facts dt{color:var(--mist)}
dl.facts dd{margin:0; font-family:var(--mono); font-size:11.5px; word-break:break-all}
.motionlist{margin-top:8px; max-height:220px; overflow:auto; border:1px solid var(--line); border-radius:2px}
.motionlist div{font-family:var(--mono); font-size:11px; padding:3px 8px; border-bottom:1px solid var(--line)}
.motionlist div:last-child{border-bottom:0}
.nav{position:absolute; top:16px; left:24px; display:flex; gap:8px; z-index:2}
.nav button, .close{background:rgba(14,21,33,.9); border:1px solid var(--line2); color:var(--bone);
  font:inherit; font-size:12px; padding:5px 11px; cursor:pointer; border-radius:2px}
.nav button:hover,.close:hover{border-color:var(--seal); color:var(--seal)}
.close{position:absolute; top:16px; right:376px; z-index:2}
.hint{position:absolute; bottom:14px; left:28px; font-family:var(--mono); font-size:11px; color:var(--mist); z-index:2}
/* ── 剧情播放器 ───────────────────────── */
.player{position:fixed; inset:0; z-index:70; display:flex; flex-direction:column; background:#05070c}
.player[hidden]{display:none}
.ptop{display:flex; align-items:center; gap:9px; padding:10px 16px; border-bottom:1px solid var(--line);
  background:rgba(7,10,17,.96); flex-wrap:wrap}
.ptop .who{font-family:var(--mincho); font-size:15px; letter-spacing:.04em}
.ptop .tm{color:var(--mist); font-size:12px; max-width:44vw; overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.ptop .sp{margin-left:auto}
.ptop button{background:var(--slate); border:1px solid var(--line2); color:var(--bone); font:inherit;
  font-size:12px; padding:5px 11px; cursor:pointer; border-radius:2px}
.ptop button:hover{border-color:var(--seal); color:var(--seal)}
.ptop button[aria-pressed="true"]{border-color:var(--seal); color:var(--seal)}
.ptop .switch{margin:0; font-size:12px}
.ptop .num{font-family:var(--mono); font-size:11px; color:var(--mist); min-width:76px; text-align:right}
.pstage{position:relative; flex:1; min-height:0; overflow:hidden; cursor:pointer;
  background:radial-gradient(circle at 50% 30%, #0d1420, #05070c 70%)}
.pbg{position:absolute; inset:0; width:100%; height:100%; object-fit:cover}
.pcharlayer{position:absolute; inset:0; overflow:hidden}
.pchara{position:absolute; bottom:-3%; transform:translateX(-50%);
  transition:left .5s ease, height .5s ease, opacity .35s ease}
.pchara.dot{bottom:19%}   /* 像素剧情:整队站在「地面线」上,不被对话框遮住下半身 */
.pchara.hid{opacity:0}    /* 未显示(载入未 show / 已 hide):淡出而不是直接消失 */
.pchara>img{display:block; height:100%; width:auto; filter:drop-shadow(0 14px 30px rgba(0,0,0,.55))}
.pchara>img.pemo{position:absolute; left:50%; top:-9%; height:20%; width:auto; transform:translateX(-50%);
  filter:drop-shadow(0 3px 9px rgba(0,0,0,.55)); pointer-events:none}
.pbox{position:absolute; left:5%; right:5%; bottom:4.5%; min-height:112px; padding:15px 20px 17px;
  background:rgba(6,9,15,.87); border:1px solid var(--line2); border-radius:3px; backdrop-filter:blur(2px)}
.pbox[hidden]{display:none}
.pname{font-family:var(--mincho); font-size:16px; color:var(--seal); letter-spacing:.07em; margin-bottom:5px; min-height:1.1em}
.ptext{font-size:16px; line-height:1.95}
.pcenter{position:absolute; inset:0; display:grid; place-items:center; padding:7% 9%; text-align:center;
  font-family:var(--mincho); font-size:19px; line-height:2.1; text-shadow:0 2px 14px #000,0 0 3px #000; white-space:pre-wrap}
.pcenter[hidden]{display:none}
.pmiss{position:absolute; left:12px; bottom:10px; font-family:var(--mono); font-size:10.5px;
  color:rgba(207,91,76,.9); max-width:48%; line-height:1.55; pointer-events:none}
.pnote{position:absolute; inset:0; display:grid; place-items:center; color:var(--mist); font-size:14px;
  text-align:center; padding:28px; white-space:pre-line}
.pstagehint{position:absolute; left:12px; top:10px; font-family:var(--mono); font-size:10.5px;
  color:var(--mist); opacity:.75; pointer-events:none; max-width:60%}
.pstagehint[hidden]{display:none}
.pnote[hidden]{display:none}
.toast{position:fixed; left:50%; bottom:34px; transform:translateX(-50%); z-index:90; background:rgba(14,21,33,.97);
  border:1px solid var(--seal); color:var(--bone); font-size:13px; padding:9px 16px; border-radius:2px; max-width:70vw}
.toast[hidden]{display:none}
@media (max-width:900px){
  .top{padding:12px 16px; gap:10px}
  .top h1{font-size:15px}
  .top h1 em{font-size:12px; letter-spacing:.1em; margin-left:7px}
  .top .stat{font-size:10px}
  .wrap{grid-template-columns:1fr}
  .rail{position:static; height:auto; border-right:0; border-bottom:1px solid var(--line); padding:16px 18px}
  .chars{flex-direction:row; flex-wrap:wrap; max-height:96px; overflow:auto}
  main{padding:18px 16px 56px}
  .viewer{grid-template-columns:1fr; grid-template-rows:minmax(0,1fr) auto}
  .info{border-left:0; border-top:1px solid var(--line); max-height:46vh}
  .close{right:16px}
  .hint{display:none}
  .nav{left:16px; top:12px}
  .nav button{padding:4px 8px; font-size:11px}
  .ptop{padding:8px 12px; gap:6px}
  .ptop .tm{max-width:100%; order:9}
  .ptop button{padding:4px 8px; font-size:11.5px}
  .pbox{left:3%; right:3%; bottom:3%; padding:11px 14px 13px; min-height:96px}
  .ptext{font-size:14.5px; line-height:1.85}
  .pcenter{font-size:16px}
}
@media (prefers-reduced-motion: reduce){*{transition:none !important; animation:none !important}}
</style>
</head>
<body>
<header class="top">
  <h1><span class="seal">◆</span>ドットアビスX<em>CG 図録</em></h1>
  <p class="stat" id="stat"></p>
</header>
<div class="wrap">
  <aside class="rail">
    <nav class="modes" id="modes"></nav>

    <section id="railAssets">
      <h2>分类 <small>可多选</small></h2>
      <div class="toggles" id="kindToggles"></div>
      <label class="switch"><input type="checkbox" id="onlyChar"> 仅角色相关</label>
      <h2>检索</h2>
      <label class="search"><input id="q" type="search" placeholder="角色 / 皮肤 / ID" autocomplete="off"></label>
      <h2 style="margin-top:22px">角色</h2>
      <div class="chars" id="chars"></div>
    </section>

    <section id="railStories" hidden>
      <h2>剧情系列</h2>
      <div class="toggles" id="seriesToggles"></div>
      <h2>角色</h2>
      <div class="chars" id="storyChars"></div>
    </section>

    <section id="railDynamic" hidden>
      <h2>动态分类</h2>
      <div class="toggles" id="dynToggles"></div>
      <p class="note" id="dynNote"></p>
    </section>
  </aside>
  <main>
    <div class="modehead" id="modehead"></div>
    <div class="grid" id="grid"></div>
    <div class="sections" id="sections"></div>
    <p class="empty" id="empty" hidden>没有匹配的素材。换个分类，或清空检索词。</p>
  </main>
</div>
<div class="viewer" id="viewer" hidden>
  <div class="nav">
    <button id="prev" type="button">← 上一个</button>
    <button id="next" type="button">下一个 →</button>
    <button id="zoom" type="button">原尺寸</button>
  </div>
  <button class="close" id="close" type="button">关闭 ✕</button>
  <div class="stage" id="stage"><div class="frame" id="frame"></div></div>
  <aside class="info" id="info"></aside>
  <p class="hint">← → 切换 · Esc 关闭 · 点击大图切换原尺寸</p>
</div>
<div class="player" id="player" hidden>
  <div class="ptop">
    <button id="pclose" type="button">关闭 ✕</button>
    <span class="who" id="pwho"></span>
    <span class="tm" id="ptm"></span>
    <span class="sp"></span>
    <button id="pprev" type="button">← 上一句</button>
    <button id="pnext" type="button">下一句 →</button>
    <button id="pauto" type="button" aria-pressed="false">自动</button>
    <label class="switch"><input type="checkbox" id="pchars" checked>角色</label>
    <span class="num" id="pnum"></span>
  </div>
  <div class="pstage" id="pstage">
    <img class="pbg" id="pbg" alt="" hidden>
    <div class="pcharlayer" id="pcharlayer"></div>
    <p class="pstagehint" id="pstagehint" hidden></p>
    <div class="pcenter" id="pcenter" hidden></div>
    <div class="pbox" id="pbox"><div class="pname" id="pname"></div><div class="ptext" id="ptext"></div></div>
    <div class="pmiss" id="pmiss"></div>
    <div class="pnote" id="pnote" hidden></div>
  </div>
</div>
<p class="toast" id="toast" hidden></p>
<script>
const DATA = __DATA__;
/* 立绘已按需求从「素材」分类中移除；charastand 数据仍保留，仅作剧情播放的角色素材 */
const ASSET_KINDS = [["cutin","cut-in"],["bg","背景"],["story","剧情图"],["icon","图标"]];
const MODES = [["assets","素材"],["stories","剧情"],["dynamic","动态"]];
const state = {
  mode:"assets",
  kinds:new Set(ASSET_KINDS.map(k=>k[0])),
  onlyChar:false, q:"", char:"",
  series:new Set((DATA.stories.series||[]).map(s=>s.key)),
  storyChar:"",
  dynKinds:new Set(["live2d","spine"]),
};
const GAL_ITEMS = DATA.items.filter(it=>it.kind!=="charastand"&&it.kind!=="emo");
const SCRIPTS = DATA.scripts||{};
const $ = s => document.querySelector(s);
const esc = s => String(s??"").replace(/[&<>"]/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const fmtSize = n => n>=1048576 ? (n/1048576).toFixed(2)+" MB" : n>=1024 ? (n/1024).toFixed(0)+" KB" : n+" B";
const USER_NAME = "司令官";  /* 脚本里的 <user> 即玩家角色 */
const PCHARA_H = 96;          /* 立绘剧情:角色高度占舞台的百分比 */
const PCHARA_H_DOT = 44;      /* 像素剧情:游戏里是整队小人,离线缩小到接近的观感 */

let toastTimer=0;
function toast(msg){
  const el=$("#toast"); el.textContent=msg; el.hidden=false;
  clearTimeout(toastTimer); toastTimer=setTimeout(()=>{ el.hidden=true; }, 3600);
}

function kindLabel(k){ const f=ASSET_KINDS.find(x=>x[0]===k); return f?f[1]:k; }
function seriesLabel(k){ const s=(DATA.stories.series||[]).find(x=>x.key===k); return s?s.label:k; }
function seriesOrder(k){ return (DATA.stories.series||[]).findIndex(x=>x.key===k); }
function charastandCover(name){
  if(!name) return "";
  const it=DATA.items.find(x=>x.kind==="charastand"&&x.character===name);
  return it?it.files[0]:"";
}
function charastandItem(art){
  return DATA.items.find(x=>x.kind==="charastand"&&x.art_id===art);
}

/* ── 顶栏统计 ─────────────────────────── */
function renderStat(){
  const d = DATA.dynamic||{}, s = DATA.stories||{};
  const dyn = (d.counts||{});
  $("#stat").textContent = (GAL_ITEMS.length+" 枚 · 剧情 "+(s.entries||[]).length+" 条 · 可播 "
    + Object.keys(SCRIPTS).length +" 话 · 动态 "
    + (dyn.live2d_models||0) +" 模型 · "+ String(DATA.generated_at||"").replace("T"," "));
}

/* ── 左栏 ─────────────────────────────── */
function renderModes(){
  const host=$("#modes"); host.innerHTML="";
  for(const [k,label] of MODES){
    const b=document.createElement("button"); b.type="button";
    b.setAttribute("aria-pressed",String(state.mode===k));
    b.textContent=label;
    b.onclick=()=>{ state.mode=k; renderRail(); renderMain(); };
    host.appendChild(b);
  }
  $("#railAssets").hidden = state.mode!=="assets";
  $("#railStories").hidden = state.mode!=="stories";
  $("#railDynamic").hidden = state.mode!=="dynamic";
}
function chip(host,label,count,pressed,onclick){
  const b=document.createElement("button"); b.type="button";
  b.setAttribute("aria-pressed",String(pressed));
  b.innerHTML = esc(label) + (count!=null?'<span class="n">'+count+'</span>':"");
  b.onclick=onclick; host.appendChild(b); return b;
}
function renderRail(){
  renderModes();
  if(state.mode==="assets"){
    const base = state.onlyChar ? GAL_ITEMS.filter(it=>it.character) : GAL_ITEMS;
    const host=$("#kindToggles"); host.innerHTML="";
    for(const [k,label] of ASSET_KINDS){
      chip(host,label,base.filter(it=>it.kind===k).length,state.kinds.has(k),()=>{
        state.kinds.has(k)?state.kinds.delete(k):state.kinds.add(k); renderRail(); renderMain(); });
    }
    const counts=new Map();
    GAL_ITEMS.forEach(it=>{ if(it.character) counts.set(it.character,(counts.get(it.character)||0)+1); });
    const list=[...counts.entries()].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0],"ja"));
    const ch=$("#chars"); ch.innerHTML="";
    const all=document.createElement("button"); all.type="button";
    all.setAttribute("aria-pressed",String(state.char===""));
    all.textContent="全部角色"; all.onclick=()=>{ state.char=""; renderRail(); renderMain(); };
    ch.appendChild(all);
    for(const [name,n] of list){
      const b=document.createElement("button"); b.type="button";
      b.setAttribute("aria-pressed",String(state.char===name));
      b.innerHTML=esc(name)+"<span>"+n+"</span>";
      b.onclick=()=>{ state.char = state.char===name?"":name; renderRail(); renderMain(); };
      ch.appendChild(b);
    }
  }
  if(state.mode==="stories"){
    const host=$("#seriesToggles"); host.innerHTML="";
    for(const s of (DATA.stories.series||[])){
      chip(host,s.label,s.count,state.series.has(s.key),()=>{
        state.series.has(s.key)?state.series.delete(s.key):state.series.add(s.key); renderRail(); renderMain(); });
    }
    const ch=$("#storyChars"); ch.innerHTML="";
    const chars=(DATA.stories.characters||[]);
    const all=document.createElement("button"); all.type="button";
    all.setAttribute("aria-pressed",String(state.storyChar===""));
    all.textContent="全部角色"; all.onclick=()=>{ state.storyChar=""; renderRail(); renderMain(); };
    ch.appendChild(all);
    for(const c of chars){
      const b=document.createElement("button"); b.type="button";
      b.setAttribute("aria-pressed",String(state.storyChar===String(c.character_id)));
      b.innerHTML=esc(c.character)+"<span>"+c.total+"</span>";
      b.onclick=()=>{ const id=String(c.character_id);
        state.storyChar = state.storyChar===id?"":id; renderRail(); renderMain(); };
      ch.appendChild(b);
    }
  }
  if(state.mode==="dynamic"){
    const d=DATA.dynamic||{}, host=$("#dynToggles"); host.innerHTML="";
    chip(host,"Live2D",(d.live2d||[]).length,state.dynKinds.has("live2d"),()=>{
      state.dynKinds.has("live2d")?state.dynKinds.delete("live2d"):state.dynKinds.add("live2d"); renderRail(); renderMain(); });
    chip(host,"Spine",(d.spine||[]).length,state.dynKinds.has("spine"),()=>{
      state.dynKinds.has("spine")?state.dynKinds.delete("spine"):state.dynKinds.add("spine"); renderRail(); renderMain(); });
    const m=d.movies||{};
    $("#dynNote").textContent = "影片（CRI 流式）：全量 "+(m.total||0)+" 部，本地实片 "+(m.local||0)
      +" 部。"+(m.note||"");
  }
}

/* ── 素材网格 ─────────────────────────── */
function matches(it){
  if(!state.kinds.has(it.kind)) return false;
  if(state.onlyChar && !it.character) return false;
  if(state.char && it.character!==state.char) return false;
  if(state.q){
    const hay=[it.art_id,it.character,it.skin,it.group,it.profile_title].filter(Boolean).join(" ").toLowerCase();
    if(!hay.includes(state.q.toLowerCase())) return false;
  }
  return true;
}
function cardTitle(it){
  if(it.character) return it.character;
  if(it.kind==="bg") return it.art_id;
  if(it.kind==="story") return it.art_id.replace(/^story_s_/,"");
  if(it.kind==="icon") return it.art_id.split("_").slice(-1)[0];
  return it.art_id;
}
function subLabel(it){
  if(it.kind==="icon") return it.group||"";
  if(it.kind==="story") return "剧情缩略图";
  return it.skin||it.group||"";
}

/* ── 主区渲染 ─────────────────────────── */
let view=[];
function renderMain(){
  const empty=$("#empty");
  const head=$("#modehead"), grid=$("#grid"), sections=$("#sections");
  sections.innerHTML=""; 
  if(state.mode==="assets"){
    head.innerHTML='<h2>素材</h2><p>'+esc([...state.kinds].map(kindLabel).join(" / ")||"（未选分类）")
      +(state.onlyChar?" · 仅角色":"")+'</p>';
    view = GAL_ITEMS.filter(matches).map(it=>({type:"asset",it}));
    grid.className="grid"+(state.kinds.size===1&&state.kinds.has("icon")?" compact":"");
    grid.hidden=false;
    grid.innerHTML = view.map((v,i)=>renderAssetCard(v.it,i)).join("");
    grid.querySelectorAll(".card").forEach(c=>c.onclick=()=>open(+c.dataset.i));
    empty.hidden = view.length>0;
    empty.textContent="没有匹配的素材。换个分类，或清空检索词。";
    return;
  }
  if(state.mode==="stories"){
    grid.hidden=true; grid.innerHTML="";
    const ents=(DATA.stories.entries||[]).filter(e=>state.series.has(e.series));
    if(!state.storyChar){
      head.innerHTML='<h2>剧情总览</h2><p>按角色聚合 · 共 '+ents.length+' 条 · 点角色名查看明细，条目可点播（▶）</p>';
      view=[];
      const chars=(DATA.stories.characters||[]);
      const list=document.createElement("div"); list.className="rowlist";
      for(const c of chars){
        const badges=(DATA.stories.series||[]).filter(s=>state.series.has(s.key)&&c.counts[s.key])
          .map(s=>'<span class="badge">'+esc(s.label)+' '+c.counts[s.key]+'</span>').join("");
        const row=document.createElement("button"); row.type="button"; row.className="row";
        row.innerHTML='<span class="no">#'+c.character_id+'</span><span><b>'+esc(c.character)+'</b>'
          +'<i>共 '+c.total+' 条剧情</i></span><span class="counts">'+badges+'</span>';
        row.onclick=()=>{ state.storyChar=String(c.character_id); renderRail(); renderMain(); };
        list.appendChild(row);
      }
      // 主线/支线没有角色归属(character_id=0),单列一行,否则无法进入
      const orphan=ents.filter(e=>!e.character_id);
      if(orphan.length){
        const counts={};
        for(const e of orphan) counts[e.series]=(counts[e.series]||0)+1;
        const badges=(DATA.stories.series||[]).filter(s=>state.series.has(s.key)&&counts[s.key])
          .map(s=>'<span class="badge">'+esc(s.label)+' '+counts[s.key]+'</span>').join("");
        const row=document.createElement("button"); row.type="button"; row.className="row";
        row.innerHTML='<span class="no">#0</span><span><b>主线・支线</b><i>共 '+orphan.length
          +' 条（无角色归属）</i></span><span class="counts">'+badges+'</span>';
        row.onclick=()=>{ state.storyChar="0"; renderRail(); renderMain(); };
        list.appendChild(row);
      }
      sections.appendChild(list);
      empty.hidden=chars.length>0;
      return;
    }
    const ch=(DATA.stories.characters||[]).find(c=>String(c.character_id)===state.storyChar);
    const mine=ents.filter(e=>String(e.character_id)===state.storyChar);
    head.innerHTML='<h2>'+esc(state.storyChar==="0"?"主线・支线":(ch?ch.character:"角色"))
      +'</h2><p>共 '+mine.length+' 条 · 点条目播放（▶ 可播）· 数量随数据</p>';
    const groups=new Map();
    for(const e of mine){ if(!groups.has(e.series)) groups.set(e.series,[]); groups.get(e.series).push(e); }
    const ordered=[...groups.entries()].sort((a,b)=>seriesOrder(a[0])-seriesOrder(b[0]));
    view=[];
    for(const [sk,list] of ordered){
      const sect=document.createElement("div"); sect.className="sect";
      sect.innerHTML='<h3>'+esc(seriesLabel(sk))+' <span class="n">'+list.length+' 条</span></h3>';
      const wrap=document.createElement("div"); wrap.className="rowlist";
      list.sort((a,b)=>(a.order||0)-(b.order||0)||a.key.localeCompare(b.key));
      for(const e of list){
        const idx=view.length; view.push({type:"story",it:e});
        const keys=scriptKeysOf(e);
        const badges=[keys.length?'<span class="badge on">▶ 播放</span>':"",
          e.chapter_name?'<span class="badge">'+esc(e.chapter_name)+'</span>':"",
          e.order&&(!e.chapter_name)?'<span class="badge">第'+e.order+'话</span>':"",
          e.unlock?'<span class="badge">絆Lv '+e.unlock+'</span>':"",
          e.r18?'<span class="badge r18">R18</span>':"",
          e.costume?'<span class="badge on">衣装</span>':""].filter(Boolean).join("");
        const row=document.createElement("button"); row.type="button"; row.className="row";
        row.innerHTML='<span class="no">'+esc(e.key.split("_")[0])+'</span><span><b>'+esc(e.title||e.key)+'</b>'
          +'<i>'+esc(e.desc||"（无简介）")+'</i></span><span class="counts">'+badges+'</span>';
        row.onclick=()=> keys.length ? playStory(keys, e) : open(idx);
        wrap.appendChild(row);
      }
      sect.appendChild(wrap); sections.appendChild(sect);
    }
    empty.hidden = mine.length>0;
    empty.textContent="该角色在当前系列筛选下没有剧情。";
    return;
  }
  /* dynamic */
  grid.hidden=false; grid.className="grid";
  head.innerHTML='<h2>动态素材</h2><p>Live2D 模型（moc3+动作+纹理）与 Spine 骨架（skel/atlas/png）</p>';
  view=[];
  const cards=[];
  for(const m of (DATA.dynamic.live2d||[])){
    if(!state.dynKinds.has("live2d")) continue;
    const idx=view.length; view.push({type:"model",kind:"live2d",it:m});
    cards.push(renderModelCard({type:"live2d",it:m},idx));
  }
  for(const m of (DATA.dynamic.spine||[])){
    if(!state.dynKinds.has("spine")) continue;
    const idx=view.length; view.push({type:"model",kind:"spine",it:m});
    cards.push(renderModelCard({type:"spine",it:m},idx));
  }
  grid.innerHTML=cards.join("");
  grid.querySelectorAll(".card").forEach(c=>c.onclick=()=>open(+c.dataset.i));
  empty.hidden = view.length>0;
  empty.textContent="本地缓存里还没有动态素材。";
}
function renderAssetCard(it,i){
  return '<button class="card" type="button" data-i="'+i+'">'
    +'<span class="thumb"><img loading="lazy" src="'+esc(it.files[0])+'" alt=""></span>'
    +'<span class="cap"><b>'+esc(cardTitle(it))+'</b><i>'+esc(subLabel(it))+'</i><u>'+esc(it.art_id)+' · '+it.size[0]+'×'+it.size[1]+'</u></span></button>';
}
function renderModelCard(v,i){
  const it=v.it;
  if(v.type==="live2d"){
    const img=charastandCover(it.character)||it.poster||(it.images||[])[0];
    const thumb = img ? '<img loading="lazy" src="'+esc(img)+'" alt="">'
      : '<span class="glyph">Live2D<small>无纹理</small></span>';
    return '<button class="card" type="button" data-i="'+i+'"><span class="thumb">'+thumb+'</span>'
      +'<span class="cap"><b>'+esc(it.character||it.model_id)+'</b><i>'+esc(it.title||it.story_key||"")+'</i>'
      +'<u>'+esc(it.model_id)+' · 动作 '+(it.motions||[]).length+' · 纹理 '+(it.textures||0)+'</u></span></button>';
  }
  const img=(it.files||[]).find(f=>f.endsWith(".png"));
  const thumb = img ? '<img loading="lazy" src="'+esc(img)+'" alt="">'
    : '<span class="glyph">Spine<small>无纹理</small></span>';
  return '<button class="card" type="button" data-i="'+i+'"><span class="thumb">'+thumb+'</span>'
    +'<span class="cap"><b>'+esc(it.boss_id)+'</b><i>剧情 Boss 骨架</i>'
    +'<u>skel '+fmtSize(it.skel_bytes||0)+' · atlas '+fmtSize(it.atlas_bytes||0)+'</u></span></button>';
}

/* ── 详情 ─────────────────────────────── */
let cur=-1, face=null, zoom=false;
function open(i){ cur=i; face=null; zoom=false; draw(); $("#viewer").hidden=false; document.body.style.overflow="hidden"; }
function close(){ $("#viewer").hidden=true; document.body.style.overflow=""; }
function step(d){ if(!view.length) return; cur=(cur+d+view.length)%view.length; face=null; zoom=false; draw(); }

function draw(){
  const v=view[cur]; if(!v) return;
  const stage=$("#stage"), frame=$("#frame");
  stage.classList.toggle("zoom", zoom);
  if(zoom){ frame.style.maxWidth="none"; frame.style.maxHeight="none"; }
  else{ frame.style.maxWidth=""; frame.style.maxHeight=""; }
  if(v.type==="asset"){
    const it=v.it;
    frame.style.aspectRatio=it.size[0]+" / "+it.size[1];
    if(zoom){ frame.style.width=it.size[0]+"px"; frame.style.height=it.size[1]+"px"; }
    else{ frame.style.width=""; frame.style.height=""; }
    if(it.kind==="charastand" && it.faces && Object.keys(it.faces).length){
      const fname=face||it.active_face||Object.keys(it.faces)[0];
      const f=it.faces[fname];
      frame.innerHTML='<img src="'+esc(it.files[0])+'" alt="" style="width:100%;height:100%">'
        + (f?'<img class="face" src="'+esc(f.file)+'" alt="" style="left:'+(f.pos[0]/it.size[0]*100)+'%;top:'+(f.pos[1]/it.size[1]*100)
            +'%;width:'+(f.size[0]/it.size[0]*100)+'%;height:'+(f.size[1]/it.size[1]*100)+'%">':"");
    }else{
      frame.style.aspectRatio="";
      frame.innerHTML='<img src="'+esc(it.files[0])+'" alt="">';
    }
    $("#info").innerHTML=assetInfoHtml(it,face);
    bindInfo();
    return;
  }
  if(v.type==="story"){
    const e=v.it;
    frame.style.aspectRatio="344 / 196";
    frame.style.width=""; frame.style.height="";
    frame.innerHTML = e.thumb_file
      ? '<img src="'+esc(e.thumb_file)+'" alt="">'
      : '<div class="placeholder">'+esc(e.key)+'<br>该剧情没有封面图</div>';
    $("#info").innerHTML=storyInfoHtml(e);
    bindInfo();
    return;
  }
  const it=v.it, isL2d=v.kind==="live2d";
  const img = isL2d ? (it.poster||(it.images||[])[0]) : (it.files||[]).find(f=>f.endsWith(".png"));
  frame.style.aspectRatio="";
  frame.style.width=""; frame.style.height="";
  frame.innerHTML = img ? '<img src="'+esc(img)+'" alt="">'
    : '<div class="placeholder">'+esc(isL2d?it.model_id:it.boss_id)+'<br>纹理尚未缓存<br>'
      +'（游戏运行时会自动补齐，重跑导出即可）</div>';
  $("#info").innerHTML=modelInfoHtml(v.kind,it);
  bindInfo();
}
function assetInfoHtml(it,fname){
  const title=it.character||cardTitle(it);
  const title2=it.profile_title?'<div class="title">'+esc(it.profile_title)+'</div>':"";
  const prof=it.profile?'<p class="desc" title="点击展开">'+esc(it.profile)+'</p>':"";
  let faces="";
  if(it.kind==="charastand" && it.faces){
    const names=Object.keys(it.faces);
    const act=fname||it.active_face;
    faces='<div class="faces"><h4>表情差分 '+names.length+'</h4><div class="row">'
      + names.map(n=>'<button type="button" data-face="'+esc(n)+'" aria-pressed="'+String(n===act)+'">'+esc(n)+'</button>').join("")
      + '</div></div>';
  }
  const facts=[["分类",it.kind],["编号",it.art_id],["尺寸",it.size[0]+"×"+it.size[1]],
    it.skin?["皮肤",it.skin]:null, it.group?["分组",it.group]:null,
    ["bundle",it.bundle||""],["缓存目录",it.cdn||""]].filter(Boolean)
    .map(([k,v])=>'<dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd>').join("");
  return '<p class="kicker">'+esc(String(it.kind).toUpperCase())+'</p><h3>'+esc(title)+'</h3>'
    +'<p class="sub">'+esc(subLabel(it))+'</p>'+title2+prof+faces+'<dl class="facts">'+facts+'</dl>';
}
function storyInfoHtml(e){
  const facts=[["系列",seriesLabel(e.series)],["编号",e.key],["角色",e.character||"—"],
    e.order?["话数","第 "+e.order+" 话"]:null, e.unlock?["解锁条件","絆 Lv "+e.unlock]:null,
    e.r18?["分级","R18"]:null, e.art_id?["立绘前缀",e.art_id]:null].filter(Boolean)
    .map(([k,v])=>'<dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd>').join("");
  const c=e.costume?('<p class="desc open">衣装：'+esc(e.costume.title)+'\n'+esc(e.costume.desc||"")+'</p>'):"";
  return '<p class="kicker">STORY</p><h3>'+esc(e.title||e.key)+'</h3>'
    +'<p class="sub">'+esc(seriesLabel(e.series))+' · '+esc(e.character||"")+'</p>'
    +'<p class="desc" title="点击展开">'+esc(e.desc||"（无简介）")+'</p>'+c+'<dl class="facts">'+facts+'</dl>';
}
function modelInfoHtml(kind,it){
  if(kind==="live2d"){
    const facts=[["类型","Live2D 模型"],["模型 ID",it.model_id],["剧情键",it.story_key||"—"],
      it.character?["角色",it.character]:null, it.title?["剧情",it.title]:null,
      ["moc3",fmtSize(it.moc3_bytes||0)],["纹理",String(it.textures||0)],["动作",String((it.motions||[]).length)]]
      .filter(Boolean).map(([k,v])=>'<dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd>').join("");
    const motions=(it.motions||[]).length
      ? '<div class="faces"><h4>动作列表</h4><div class="motionlist">'
        + (it.motions||[]).map(n=>'<div>'+esc(n)+'</div>').join("")+'</div></div>' : "";
    return '<p class="kicker">LIVE2D</p><h3>'+esc(it.character||it.model_id)+'</h3>'
      +'<p class="sub">'+esc(it.title||"")+'</p><dl class="facts">'+facts+'</dl>'+motions
      +'<p class="note" style="margin-top:18px">文件：live2d/'+esc(it.model_id)+'/（moc3 + motion3.json + 纹理，标准格式，可用 Cubism 运行时离线播放）<br>'
      +'此处展示的是模型图集（绘制序纹理），非渲染效果；渲染需要 Cubism Web 运行时。</p>';
  }
  const facts=[["类型","Spine 骨架"],["Boss ID",it.boss_id],["skel",fmtSize(it.skel_bytes||0)],
    ["atlas",fmtSize(it.atlas_bytes||0)],["纹理",String(it.textures||0)]]
    .map(([k,v])=>'<dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd>').join("");
  return '<p class="kicker">SPINE</p><h3>'+esc(it.boss_id)+'</h3><p class="sub">剧情 Boss 骨骼动画</p>'
    +'<dl class="facts">'+facts+'</dl>'
    +'<p class="note" style="margin-top:18px">文件：spine/'+esc(it.boss_id)+'/（.skel + .atlas + .png，标准格式，可用 Spine 运行时离线播放）</p>';
}
/* ── 剧情播放器 ───────────────────────── */
const PLAY = {ev:[],i:0,chars:new Map(),bg:"",timer:0,auto:false,missing:new Set(),dotStage:false};
function scriptKeysOf(e){
  if(!e) return [];
  const alt=e.key.slice(0,-1)+"2";            /* 末位 1=前篇、2=后篇 */
  return [e.key, alt].filter(k=>SCRIPTS[k]);
}
function faceName(v){
  const raw=String(v||"").trim();
  if(!raw) return "";
  if(/^EyeClose$/i.test(raw)) return "Closed";
  if(/^EyeOpen$/i.test(raw)) return "";
  const name=raw.replace(/^Face/,"").toLowerCase();
  const known=["Normal","Happy","Sad","Anger","Fun","Shy","Surprise","Closed","Deco",
    "Unique01","Unique02","Unique03","Unique04","Unique05","Unique06","Unique07"];
  for(const k of known) if(k.toLowerCase()===name) return k;
  return "";
}
function dtext(s){
  const raw=String(s??"").replace(/<user>/g,USER_NAME);   /* 脚本里的玩家角色占位符 */
  return esc(raw).replace(/\n/g,"<br>").replace(/&lt;br\s*\/?&gt;/gi,"<br>")
    .replace(/&lt;[^&]{0,40}?&gt;/g,"");                  /* 去掉 <size=..> 之类标签 */
}
function textIdx(from,dir){
  let j=from;
  while(j>=0&&j<PLAY.ev.length){
    if(PLAY.ev[j][0]==="m"||PLAY.ev[j][0]==="n") return j;
    j+=dir;
  }
  return -1;
}
function replayTo(i){
  PLAY.chars=new Map(); PLAY.bg=""; PLAY.beats=0;
  for(let k=0;k<i;k++){
    const e=PLAY.ev[k], t=e[0];
    if(t==="b") PLAY.bg=e[1];
    else if(t==="+") PLAY.chars.set(e[1],{art:e[2],name:e[3],mob:e[4],x:50,y:0,s:1,face:"",emo:"",emoMode:"",emoBeat:0,shown:!e[5]});
    else if(t==="x"){ const c=PLAY.chars.get(e[1]); if(c) c.x=e[2]; }
    else if(t==="y"){ const c=PLAY.chars.get(e[1]); if(c) c.y=e[2]; }
    else if(t==="s"){ const c=PLAY.chars.get(e[1]); if(c) c.s=e[2]; }
    else if(t==="f"){ const c=PLAY.chars.get(e[1]); if(c) c.face=e[2]; }
    else if(t==="e"){
      if(e[1]==="*"){ for(const [,x] of PLAY.chars){ x.emo=""; } }
      else { const c=PLAY.chars.get(e[1]); if(c){ c.emo=e[2]; c.emoMode=e[3]; c.emoBeat=PLAY.beats; } }
    }
    else if(t==="h"){ const c=PLAY.chars.get(e[1]); if(c) c.shown=false; }
    else if(t==="sh"){ const c=PLAY.chars.get(e[1]); if(c) c.shown=true; }
    else if(t==="clr") PLAY.chars=new Map();
    if(t==="m"||t==="n") PLAY.beats++;
  }
}
function markMissing(label){
  if(PLAY.missing.has(label)) return;
  PLAY.missing.add(label);
  $("#pmiss").textContent="素材未缓存："+[...PLAY.missing].slice(0,6).join("・")+(PLAY.missing.size>6?" 等":"");
}
function renderPlayer(){
  const e=PLAY.ev[PLAY.i]||["n",""];
  replayTo(PLAY.i);
  const total=PLAY.ev.filter(x=>x[0]==="m"||x[0]==="n").length;
  const cur=PLAY.beats+((e[0]==="m"||e[0]==="n")?1:0);   /* 当前位置本身就是一段文本,计入 */
  const bg=$("#pbg");
  const it=PLAY.bg?DATA.items.find(x=>x.kind==="bg"&&x.art_id===PLAY.bg):null;
  /* 20×20 之类的纯色占位图(游戏里当底色叠加像素舞台用)不铺满,回落到舞台底色 */
  const tiny=!!(it&&it.size&&Math.min(it.size[0],it.size[1])<64);
  if(PLAY.bg&&!tiny){
    const src="bg/"+PLAY.bg+".png";
    if(bg.getAttribute("src")!==src) bg.setAttribute("src",src);
    bg.hidden=false;
  } else { bg.hidden=true; bg.removeAttribute("src"); }
  const hint=$("#pstagehint");
  hint.hidden = !(PLAY.dotStage&&(tiny||!PLAY.bg));   /* 像素剧情背景是运行时 3D 舞台 */
  if(!hint.hidden) hint.textContent="背景：运行时 3D 舞台（离线不可复现，仅角色与文本）";
  const layer=$("#pcharlayer"); layer.innerHTML="";
  if($("#pchars").checked){
    for(const [,c] of PLAY.chars){
      if(c.mob) continue;                           /* 像素单位是 Spine,离线无法渲染 */
      const holder=document.createElement("div");
      holder.className="pchara"+(PLAY.dotStage?" dot":"")+(c.shown?"":" hid");
      holder.style.left=c.x+"%";                    /* 解析期已归一到舞台百分比 */
      const base=PLAY.dotStage?PCHARA_H_DOT:PCHARA_H;
      holder.style.height=Math.max(base/4,base*c.s)+"%";
      const img=document.createElement("img");
      img.src="charastand/"+c.art+".png"; img.alt="";
      img.onerror=()=>{ holder.style.display="none"; markMissing("立绘 "+c.art); };
      holder.appendChild(img);
      const item=charastandItem(c.art), fn=faceName(c.face);
      if(item&&item.size&&item.faces&&item.faces[fn]){
        const f=item.faces[fn];
        const fi=document.createElement("img");
        fi.src=f.file; fi.alt="";
        fi.style.cssText="position:absolute;left:"+(f.pos[0]/item.size[0]*100)+"%;top:"+(f.pos[1]/item.size[1]*100)
          +"%;width:"+(f.size[0]/item.size[0]*100)+"%;height:"+(f.size[1]/item.size[1]*100)+"%";
        fi.onerror=()=>fi.remove();
        holder.appendChild(fi);
      }
      /* 情绪符号:STOP 只演一段,CONT 持续到被替换(与游戏 cemo 一致) */
      if(c.emo&&(c.emoMode!=="STOP"||cur-c.emoBeat<=1)){
        const ei=document.createElement("img");
        ei.className="pemo"; ei.src="emo/"+String(c.emo).toLowerCase()+".png"; ei.alt="";
        ei.onerror=()=>ei.remove();
        holder.appendChild(ei);
      }
      layer.appendChild(holder);
    }
  }
  const box=$("#pbox"), center=$("#pcenter");
  if(e[0]==="m"){
    box.hidden=false; center.hidden=true;
    const raw=String(e[1]||"");
    $("#pname").textContent = raw==="<user>" ? USER_NAME : raw;
    $("#ptext").innerHTML = dtext(e[2]);
  } else {
    box.hidden=true; center.hidden=false;
    center.innerHTML = dtext(e[1]);
  }
  $("#pnum").textContent=cur+" / "+total;
}
function stepPlay(dir){
  const j=textIdx(PLAY.i+dir,dir);
  if(j<0) return;
  PLAY.i=j; renderPlayer();
}
function loadScripts(keys){
  const jobs=keys.filter(k=>!(window.STORY&&window.STORY[k])).map(k=>new Promise((res,rej)=>{
    const s=document.createElement("script");
    s.src=(SCRIPTS[k]||{}).file||("stories/"+k+".js");   /* file:// 下 fetch 被拦,用 script 标签 */
    s.onload=()=>res(); s.onerror=()=>rej(new Error(k));
    document.head.appendChild(s);
  }));
  return Promise.all(jobs);
}
function setAuto(on){
  PLAY.auto=on; $("#pauto").setAttribute("aria-pressed",String(on));
  clearInterval(PLAY.timer);
  if(on) PLAY.timer=setInterval(()=>{
    const j=textIdx(PLAY.i+1,1);
    if(j<0){ setAuto(false); return; }
    PLAY.i=j; renderPlayer();
  }, 2300);
}
function playStory(keys,e){
  loadScripts(keys).then(()=>{
    const ev=[];
    keys.forEach((k,idx)=>{
      const d=window.STORY&&window.STORY[k];
      if(!d) return;
      if(idx>0) ev.push(["n","―― 後篇 ――","c"]);
      for(const x of d.ev) ev.push(x);
    });
    if(!ev.length){ toast("这条剧情的脚本是空的"); return; }
    PLAY.ev=ev; PLAY.missing=new Set(); PLAY.bg=""; PLAY.dotStage=false;
    keys.forEach(k=>{ const d=window.STORY&&window.STORY[k]; if(d&&d.dot_stage) PLAY.dotStage=true; });
    $("#pmiss").textContent=""; setAuto(false);
    $("#pwho").textContent=[e.character,e.chapter_name].filter(Boolean).join(" · ");
    $("#ptm").textContent=(e.title||e.key)+"（"+e.key+"）";
    $("#player").hidden=false;
    const j=textIdx(0,1);
    PLAY.i=j<0?0:j;
    renderPlayer();
  }).catch(()=>toast("脚本载入失败：stories/ 下的脚本文件缺失"));
}
function closePlayer(){ $("#player").hidden=true; PLAY.ev=[]; setAuto(false); }
function bindInfo(){
  $("#info").querySelectorAll("[data-face]").forEach(b=>b.onclick=()=>{ face=b.dataset.face; draw(); });
  const p=$("#info").querySelector(".desc"); if(p) p.onclick=()=>p.classList.toggle("open");
}
$("#q").addEventListener("input", e=>{ state.q=e.target.value.trim(); renderMain(); });
$("#onlyChar").addEventListener("change", e=>{ state.onlyChar=e.target.checked; renderRail(); renderMain(); });
$("#close").onclick=close;
$("#prev").onclick=()=>step(-1);
$("#next").onclick=()=>step(1);
$("#zoom").onclick=()=>{ zoom=!zoom; $("#zoom").textContent=zoom?"适应窗口":"原尺寸"; draw(); };
$("#stage").onclick=e=>{ if(e.target.tagName==="IMG"){ zoom=!zoom; $("#zoom").textContent=zoom?"适应窗口":"原尺寸"; draw(); } };
$("#pclose").onclick=closePlayer;
$("#pprev").onclick=()=>stepPlay(-1);
$("#pnext").onclick=()=>stepPlay(1);
$("#pauto").onclick=()=>setAuto(!PLAY.auto);
$("#pchars").addEventListener("change",renderPlayer);
$("#pstage").onclick=()=>{ stepPlay(1); };
document.addEventListener("keydown", e=>{
  if(!$("#player").hidden){
    if(e.key==="Escape") closePlayer();
    else if(e.key==="ArrowRight"||e.key===" "||e.key==="Enter"){ e.preventDefault(); stepPlay(1); }
    else if(e.key==="ArrowLeft") stepPlay(-1);
    return;
  }
  if($("#viewer").hidden) return;
  if(e.key==="Escape") close();
  else if(e.key==="ArrowLeft") step(-1);
  else if(e.key==="ArrowRight") step(1);
});
renderStat(); renderRail(); renderMain();
</script>
</body>
</html>
"""


def _slim_dynamic(dyn: dict) -> dict:
    """裁剪动态数据:动作只留名字、只保留 png 文件,控制单文件体积。"""
    out = {"counts": dyn.get("counts", {}), "movies": dyn.get("movies", {}), "live2d": [], "spine": []}
    for e in dyn.get("live2d", []):
        slim = {
            "model_id": e.get("model_id", ""),
            "story_key": e.get("story_key", ""),
            "moc3_bytes": e.get("moc3_bytes", 0),
            "textures": e.get("textures", 0),
            "character": e.get("character", ""),
            "character_id": e.get("character_id", 0),
            "title": e.get("title", ""),
            "poster": e.get("poster", ""),
            "images": [f for f in e.get("files", []) if f.endswith(".png")],
            "motions": [m.get("name", "") for m in e.get("motions", [])],
        }
        out["live2d"].append(slim)
    for e in dyn.get("spine", []):
        out["spine"].append({
            "boss_id": e.get("boss_id", ""),
            "skel_bytes": e.get("skel_bytes", 0),
            "atlas_bytes": e.get("atlas_bytes", 0),
            "textures": e.get("textures", 0),
            "files": [f for f in e.get("files", []) if f.endswith(".png")],
        })
    return out


def _slim_scripts(scripts: dict) -> dict:
    """裁剪脚本清单:播放器只需要脚本文件路径与段数。"""
    return {key: {"file": v.get("file", ""), "beats": v.get("beats", 0)}
            for key, v in (scripts or {}).items()}


def build(manifest_path: Path, out_path: Path) -> None:
    """读 manifest.json 并写出单文件图库。

    Args:
        manifest_path: 导出产物的 manifest.json。
        out_path: 目标 gallery.html 路径。
    """
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    payload_data = {
        "generated_at": manifest.get("generated_at", ""),
        "counts": manifest.get("counts", {}),
        "items": manifest.get("items", []),
        "stories": manifest.get("stories", {}),
        "dynamic": _slim_dynamic(manifest.get("dynamic") or {}),
        "scripts": _slim_scripts(manifest.get("scripts") or {}),
    }
    payload = json.dumps(payload_data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    html_text = TEMPLATE.replace("__DATA__", payload)
    Path(out_path).write_text(html_text, encoding="utf-8")


def main() -> None:
    """入口:从默认输出目录生成 gallery.html。"""
    root = Path(__file__).resolve().parent.parent
    out = root / "output"
    build(out / "manifest.json", out / "gallery.html")
    print(f"已生成:{out / 'gallery.html'}")


if __name__ == "__main__":
    main()
