"""Создать один автономный HTML из сохранённых результатов исследования Кореновска.

Запуск из корня проекта: python3 build_dashboard.py
Скрипт не обращается к сети, не импортирует BlocksNet и не пересчитывает его показатели.
Требуется только стандартная библиотека Python 3.10+. Карта без сетевой подложки работает офлайн.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import math
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_RESULTS = ROOT / "examples" / "data" / "korenovsk" / "results"
DEFAULT_OUTPUT = ROOT / "dashboard.html"

METRICS = [
    {"key": "land_use", "label": "Функциональное назначение", "kind": "category", "unit": "",
     "help": "Преобладающее использование по OSM. Не является официальным градостроительным зонированием."},
    {"key": "fsi", "label": "FSI · интенсивность застройки", "kind": "number", "unit": "м²/м²",
     "help": "Сумма площадей этажей / площадь квартала. Зависит от полноты зданий и предположений об этажности."},
    {"key": "gsi", "label": "GSI · доля пятен застройки", "kind": "number", "unit": "доля",
     "help": "Сумма площадей оснований зданий / площадь квартала. 0,3 означает 30%."},
    {"key": "mxi", "label": "MXI · доля жилой площади", "kind": "number", "unit": "доля",
     "help": "Жилая / поэтажная площадь. Неизвестное назначение зданий ограничивает достоверность."},
    {"key": "l", "label": "L · модельная средняя этажность", "kind": "number", "unit": "этажей",
     "help": "Поэтажная площадь / пятно застройки. Взвешенная оценка; пропущенная этажность заменялась предположением."},
    {"key": "osr", "label": "OSR · открытое пространство", "kind": "number", "unit": "м²/м²",
     "help": "(Площадь квартала − пятна зданий) / поэтажная площадь. Не измеряет озеленение или благоустройство."},
    {"key": "population_density_per_ha", "label": "Модельная плотность населения", "kind": "number",
     "unit": "жителей/га", "help": "Сохранённая модельная оценка населения / площадь всего квартала в гектарах. Не перепись."},
    {"key": "spacematrix_morphotype", "label": "Морфотип Spacematrix", "kind": "category", "unit": "",
     "help": "Группировка по FSI, L и MXI. Зависит от выборки и качества исходных данных; не оценка качества среды."},
    {"key": "strelka_morphotype", "label": "Морфотип «Стрелки»", "kind": "category", "unit": "",
     "help": "Модельная классификация по порогам FSI, L и MXI; не результат обследования зданий."},
    {"key": "schools_count", "label": "Количество школ в OSM", "kind": "number", "unit": "объектов",
     "help": "Количество проверенных школьных объектов, отнесённых к кварталу. Ноль в слое не доказывает отсутствие школы."},
    {"key": "capacity", "label": "Модельная вместимость школ", "kind": "number", "unit": "мест",
     "help": "Сумма сохранённых вместимостей. Для пропусков использовалось типовое значение; это не проверенное число мест."},
]


HTML = r'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Кореновск — учебное исследование BlocksNet</title>
<style>
:root{--ink:#18352f;--muted:#5e706a;--paper:#f3f5ef;--card:#fff;--line:#dce3da;--accent:#166b54;--amber:#fff2d6}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.6 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header,main,footer{max-width:1440px;margin:auto;padding:28px 32px}header{padding-top:42px;padding-bottom:20px}
.eyebrow{font-size:12px;letter-spacing:.13em;text-transform:uppercase;color:var(--accent);font-weight:750}
h1{font-size:clamp(30px,4vw,52px);line-height:1.15;letter-spacing:-.04em;margin:10px 0}h2{font-size:23px;letter-spacing:-.025em;margin:0 0 14px}h3{font-size:17px;margin:0 0 10px}p{margin:8px 0 14px}.muted,small{color:var(--muted)}
.tag{display:inline-block;border:1px solid var(--line);border-radius:20px;padding:3px 11px;font-size:12px;margin:4px 6px 0 0;background:white}
.notice{border:1px solid #ead7ab;background:var(--amber);padding:16px 20px;border-radius:14px;margin:0 0 22px}.notice strong{display:block}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:26px}.kpi,.panel{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:22px}.kpi .value{font-size:32px;font-weight:750;line-height:1.2;margin:10px 0}.kpi .label{font-size:13px;color:var(--muted)}
.layout{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(300px,1fr);gap:20px}.panel{margin-bottom:22px;min-width:0}.toolbar{display:flex;gap:12px;align-items:end;flex-wrap:wrap;margin-bottom:12px}label{display:block;font-size:13px;font-weight:650}
select,input,button{font:inherit;border:1px solid #cbd6cd;border-radius:9px;padding:8px 11px;background:#fff;color:var(--ink)}select{max-width:100%;width:100%}select:focus,input:focus,button:focus,a:focus{outline:3px solid #80c9b4;outline-offset:2px}button{cursor:pointer}button:hover{background:#e9f2ec}.toolbar .grow{flex:1;min-width:220px}.map-wrap{position:relative;background:#f1f4ee;border:1px solid var(--line);border-radius:12px;overflow:hidden}
#map{display:block;width:100%;height:580px;touch-action:none;cursor:grab}#map.dragging{cursor:grabbing}.block{stroke:#fff;stroke-width:1;vector-effect:non-scaling-stroke;cursor:pointer}.block:hover{stroke:#173b30;stroke-width:2}.block.selected{stroke:#132c25;stroke-width:3}.block.dimmed{opacity:.18}.map-actions{position:absolute;top:12px;right:12px;display:flex;gap:5px}.map-caption{font-size:12px;color:var(--muted);margin-top:8px}.legend{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px;font-size:12px}.legend span{display:inline-flex;align-items:center;gap:5px}.swatch{display:inline-block;width:13px;height:13px;border-radius:3px;border:1px solid #0001}.detail{background:#f4f7f2;border:1px solid var(--line);border-radius:12px;padding:15px;margin-top:18px}.detail dl{display:grid;grid-template-columns:1fr 1fr;gap:5px 12px;font-size:13px;margin:8px 0}.detail dt{color:var(--muted)}.detail dd{margin:0;text-align:right;overflow-wrap:anywhere}.unavailable{background:#f7f6f2;border:1px dashed #c8c8ba;padding:14px;border-radius:12px;margin:10px 0}.unavailable b{display:block}.status{color:#7c5c18;font-size:12px}
#distribution{min-height:210px}.bar-row{display:grid;grid-template-columns:145px 1fr 35px;gap:8px;align-items:center;font-size:12px;margin:9px 0}.bar-track{height:13px;background:#eff3ed;border-radius:4px;overflow:hidden}.bar-fill{height:100%;background:var(--accent);border-radius:4px}.table-wrap{overflow:auto;max-height:550px;border:1px solid var(--line);border-radius:10px}table{border-collapse:collapse;width:100%;font-size:13px;white-space:nowrap}th,td{padding:10px 12px;border-bottom:1px solid #e4e9e1;text-align:right}th:first-child,td:first-child{text-align:left}th{position:sticky;top:0;background:#edf3eb;z-index:1}th button{border:none;background:none;font-size:12px;padding:0;white-space:nowrap}tbody tr:hover,tbody tr.active{background:#e7f2e9}.row-link{padding:1px 6px;color:var(--accent);font-weight:700}.table-tools{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:10px 0}.table-tools input{width:230px}.quality-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.facts{margin:0;padding-left:20px}.facts li{margin:8px 0}.missing{color:#7b8580}.figures{display:grid;grid-template-columns:1fr 1fr;gap:16px}.figures figure{margin:0;border:1px solid var(--line);border-radius:10px;padding:12px}.figures img{width:100%;height:auto}.figures figcaption{font-size:12px;color:var(--muted)}details>summary{cursor:pointer;font-weight:650;margin-bottom:14px}.export-link{color:var(--accent);font-weight:650;margin-right:18px}.explanation{font-size:13px;color:var(--muted);min-height:42px}.quality-table{white-space:normal}.quality-table td{text-align:left;overflow-wrap:anywhere}.quality-table th{text-align:left;position:static}footer{font-size:12px;color:var(--muted);border-top:1px solid var(--line)}.print-button{float:right}
@media(max-width:1000px){.layout{grid-template-columns:1fr}.kpis{grid-template-columns:1fr 1fr}#map{height:500px}}
@media(max-width:600px){header,main,footer{padding:20px 16px}.kpis,.quality-grid,.figures{grid-template-columns:1fr}.panel{padding:16px}#map{height:410px}.bar-row{grid-template-columns:110px 1fr 30px}.print-button{float:none}}
@media print{body{background:white;font-size:11px}header,main,footer{max-width:none;padding:12px}.layout,.quality-grid{display:block}.panel,.kpi{break-inside:avoid;border-radius:0}.toolbar,.map-actions,.print-button,.table-tools,.downloads{display:none}#map{height:460px}.table-wrap{max-height:none;overflow:visible}th{position:static}.figures{display:block}.figures figure{break-inside:avoid}details:not([open]){display:none}}
</style>
</head>
<body>
<header><span class="eyebrow">Практическая работа · BlocksNet <span id="version"></span></span>
<button class="print-button" type="button" onclick="window.print()">Печать / PDF</button>
<h1>Кореновск: структура городской территории</h1>
<p class="muted">Кварталы, застройка и социальные объекты · Краснодарский край, Россия</p>
<span class="tag">Учебная модель</span><span class="tag">Сохранённые результаты</span><span class="tag">Карта работает офлайн</span>
</header>
<main>
<div class="notice"><strong>Модельные оценки — не фактическая характеристика населения города</strong>
Неполнота OSM ограничивает сведения об этажности и жилом назначении зданий. Население, площади помещений,
часть вместимостей школ и морфотипы основаны на допущениях. Их нельзя использовать как официальную статистику.</div>
<div class="kpis" id="kpis"></div>
<div class="layout">
<section class="panel"><h2>Карта кварталов</h2>
<div class="toolbar"><div class="grow"><label for="metric">Показатель окраски</label><select id="metric"></select></div>
<div><label for="landFilter">Назначение</label><select id="landFilter"></select></div></div>
<p class="explanation" id="metricHelp"></p>
<div class="map-wrap"><svg id="map" viewBox="0 0 1000 650" role="img" aria-label="Интерактивная карта кварталов Кореновска"><g id="mapGroup"></g></svg>
<div class="map-actions"><button id="zoomIn" aria-label="Приблизить">+</button><button id="zoomOut" aria-label="Отдалить">−</button><button id="resetMap">Весь город</button></div></div>
<div class="map-caption">Колесо — масштаб; перетаскивание — перемещение; щелчок — карточка квартала. Без фоновой карты и сетевых запросов. Серый цвет означает отсутствие значения.</div>
<div class="legend" id="legend"></div>
</section>
<aside><section class="panel"><h2>Распределение показателя</h2><p class="muted" id="chartCaption"></p><div id="distribution"></div><small id="chartMissing"></small>
<div class="detail" id="detail" aria-live="polite"><h3>Выберите квартал на карте</h3><p class="muted">Или нажмите его номер в таблице. Карточка показывает сохранённые значения.</p></div></section>
<section class="panel"><h3>Транспортные показатели</h3>
<div class="unavailable"><b>Время в пути — недоступно</b><span class="status">Готовый транспортный граф не получен.</span></div>
<div class="unavailable"><b>Обеспеченность школами — недоступна</b><span class="status">Количество мест не равно обеспеченности с учётом времени и конкуренции.</span></div>
<div class="unavailable"><b>area_accessibility — недоступен</b><span class="status">Нет матрицы времени между кварталами.</span></div>
<small>Отсутствие расчёта не заменяется нулём, расстоянием по прямой или условным временем. Разделы 10–11 не выполнены.</small></section></aside>
</div>
<section class="panel"><h2>Таблица показателей BlocksNet</h2>
<p class="muted">Все значения прочитаны из сохранённых файлов. Нажмите заголовок для сортировки. Фильтр назначения общий с картой.</p>
<div class="table-tools"><label for="search">Номер квартала</label><input id="search" type="search" placeholder="Например, 125"><span id="rowCount" class="muted"></span></div>
<div class="table-wrap"><table id="metricsTable"><thead></thead><tbody></tbody></table></div>
<p class="downloads"><a id="csvDownload" class="export-link" download="blocks_indicators.csv">Скачать исходную таблицу CSV</a><a id="geoDownload" class="export-link" download="blocks_indicators.geojson">Скачать исходный GeoJSON</a></p>
</section>
<section class="panel"><h2>Качество данных и ограничения</h2><div class="quality-grid"><div><h3>Что известно о данных</h3><ul class="facts" id="qualityFacts"></ul></div><div><h3>Ограничения автоматической нарезки</h3><ul class="facts" id="cuttingFacts"></ul></div></div>
<details><summary>Допущения, происхождение и сохранённый отчёт</summary><div id="assumptions"></div><div class="table-wrap"><table class="quality-table"><tbody id="reportTable"></tbody></table></div></details>
</section>
<section class="panel"><h2>Краткие выводы</h2><ol class="facts" id="conclusions"></ol></section>
<section class="panel"><details><summary>Графики, сохранённые при выполнении ноутбука</summary><p class="muted">Встроены существующие PNG. Новые исследовательские расчёты не выполнялись. Текущий фильтр карты на эти изображения не влияет.</p><div class="figures" id="savedFigures"></div></details></section>
</main>
<footer><p>Учебное исследование только города Кореновска. Источник объектов — © OpenStreetMap contributors, ODbL. Методика — BlocksNet 1.0.0a9 и pipeline.ipynb. Дата формирования страницы: <span id="generated"></span>.</p>
<p>Одна автономная HTML-страница: данные, интерфейс и графики встроены. Цвета и распределения используются только для представления готовых значений. Городские показатели не пересчитываются.</p></footer>
<script id="dashboardData" type="application/json">__DASHBOARD_DATA__</script>
<script>
'use strict';
const DATA=JSON.parse(document.getElementById('dashboardData').textContent);
const el=id=>document.getElementById(id), SVG='http://www.w3.org/2000/svg';
const features=DATA.geojson.features, metrics=DATA.metrics, report=DATA.report;
const fmt=(v,d=2)=>v===null||v===undefined?'Нет данных':typeof v==='number'?v.toLocaleString('ru-RU',{maximumFractionDigits:d}):String(v);
const num=v=>{if(v===null||v===undefined||v===''||typeof v==='boolean')return null;const n=Number(v);return Number.isFinite(n)?n:null};
const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n};
const titles={residential:'Жилая',business:'Деловая',industrial:'Промышленная',recreation:'Рекреационная',agriculture:'Сельскохозяйственная',transport:'Транспортная',special:'Специальная'};
const typeText=v=>{if(v===null||v===undefined||v==='')return 'Нет данных';if(titles[v])return titles[v];return String(v).replaceAll('high-mid-rise','среднеповышенная этажность').replaceAll('low-rise','малоэтажная').replaceAll('mid-rise','среднеэтажная').replaceAll('high-rise','многоэтажная').replaceAll('non-residential','нежилая').replaceAll('low-density','низкая плотность').replaceAll('high-density','высокая плотность').replaceAll('mixed-use','смешанная').replaceAll('residential','жилая').replaceAll('individual','индивидуальная').replaceAll('soviet','советский').replaceAll('modern','современный').replaceAll('microdistrict','микрорайон').replaceAll('central model','центральная модель').replaceAll('model','типовая').replaceAll('block','квартальная').replaceAll('tower','высотная')};
const val=(p,m)=>m.kind==='category'?typeText(p[m.key]):fmt(num(p[m.key]),m.key==='schools_count'||m.key==='capacity'?0:3);
const addFact=(parent,text)=>parent.append(node('li',text));
el('version').textContent=report.versions?.blocksnet||'1.0.0a9';el('generated').textContent=DATA.generated;
const kpis=[['Кварталы исследуемой территории',features.length,'Автоматическая нарезка, без ручной корректировки'],['Модельная оценка жителей',report.estimated_population_in_blocks,'Не фактическая численность города'],['Этажность подставлена',report.floors_estimated_buildings,'Зданий с модельной этажностью'],['Неизвестно жилое назначение',report.residential_unknown_buildings,'Зданий с недостаточными тегами OSM']];
for(const [label,value,caption]of kpis){const card=node('div',undefined,'kpi');card.append(node('div',label,'label'),node('div',fmt(value,0),'value'),node('small',caption));el('kpis').append(card)}
for(const m of metrics){const o=node('option',m.label);o.value=m.key;el('metric').append(o)}
const all=node('option','Все назначения');all.value='';el('landFilter').append(all);
const landValues=[...new Set(features.map(f=>f.properties.land_use??''))].sort();
for(const v of landValues){const o=node('option',typeText(v));o.value=v||'__missing';el('landFilter').append(o)}
let metric=metrics.find(m=>m.key==='fsi'),selected=null,sortKey='block_id',sortAsc=true;
el('metric').value=metric.key;
const palette=['#2a6b54','#729d78','#c8ad55','#a2694c','#6a829d','#8a7594','#b7aa94','#557d79','#9e6971','#7c8753','#9b814c','#5c6689'];
const missingColor='#cbd2cb',numberPalette=['#e0eee5','#b3d4bd','#7fb395','#43866c','#185542'];
let colorFor=()=>missingColor;
function visible(f){const filter=el('landFilter').value;return !filter||(filter==='__missing'? !f.properties.land_use:f.properties.land_use===filter)}
function filtered(){return features.filter(visible)}
function updateScale(){const rows=filtered();el('legend').replaceChildren();if(metric.kind==='category'){
 const categories=[...new Set(rows.map(f=>f.properties[metric.key]).filter(v=>v!==null&&v!==undefined&&v!==''))].sort();
 const colors=new Map(categories.map((v,i)=>[v,palette[i%palette.length]]));colorFor=v=>colors.get(v)||missingColor;
 for(const v of categories)addLegend(colorFor(v),typeText(v));
 }else{const values=rows.map(f=>num(f.properties[metric.key])).filter(v=>v!==null);let lo=values.length?Math.min(...values):0,hi=values.length?Math.max(...values):0;
 colorFor=v=>{v=num(v);if(v===null)return missingColor;return numberPalette[hi===lo?2:Math.min(4,Math.max(0,Math.floor((v-lo)/(hi-lo)*5)))]};
 if(values.length){if(lo===hi)addLegend(numberPalette[2],fmt(lo,3));else for(let i=0;i<5;i++){const a=lo+(hi-lo)*i/5,b=lo+(hi-lo)*(i+1)/5;addLegend(numberPalette[i],fmt(a,3)+' – '+fmt(b,3))}}
 }addLegend(missingColor,'Нет данных');el('metricHelp').textContent=metric.help+(metric.unit?' Единица: '+metric.unit+'.':'');
}
function addLegend(color,label){const s=node('span'),sw=node('i',undefined,'swatch');sw.style.background=color;s.append(sw,document.createTextNode(label));el('legend').append(s)}
// Преобразование координат только для экранного рисунка. Площади/плотности из геометрии не вычисляются.
let minLon=Infinity,maxLon=-Infinity,minLat=Infinity,maxLat=-Infinity;
function walk(c){if(typeof c[0]==='number'){minLon=Math.min(minLon,c[0]);maxLon=Math.max(maxLon,c[0]);minLat=Math.min(minLat,c[1]);maxLat=Math.max(maxLat,c[1])}else for(const p of c)walk(p)}
features.forEach(f=>walk(f.geometry.coordinates));
const latitude=(minLat+maxLat)/2*Math.PI/180,cos=Math.cos(latitude),worldW=Math.max((maxLon-minLon)*cos,1e-9),worldH=Math.max(maxLat-minLat,1e-9),scale=Math.min(900/worldW,560/worldH);
function xy(c){return[50+(c[0]-minLon)*cos*scale+(900-worldW*scale)/2,45+(maxLat-c[1])*scale+(560-worldH*scale)/2]}
function ring(coords){return coords.map((p,i)=>(i?'L':'M')+xy(p).map(x=>x.toFixed(2)).join(',')).join(' ')+'Z'}
function shape(g){return(g.type==='Polygon'?[g.coordinates]:g.coordinates).map(poly=>poly.map(ring).join(' ')).join(' ')}
const mapPaths=new Map();
for(const f of features){const p=document.createElementNS(SVG,'path');p.setAttribute('d',shape(f.geometry));p.setAttribute('fill-rule','evenodd');p.classList.add('block');const title=document.createElementNS(SVG,'title');p.append(title);p.addEventListener('click',()=>{if(!dragMoved)selectBlock(f.properties.block_id)});mapPaths.set(f.properties.block_id,{path:p,title,feature:f});el('mapGroup').append(p)}
function drawMap(){for(const {path,title,feature:f} of mapPaths.values()){path.setAttribute('fill',colorFor(f.properties[metric.key]));path.classList.toggle('dimmed',!visible(f));path.classList.toggle('selected',f.properties.block_id===selected);title.textContent='Квартал '+f.properties.block_id+' · '+metric.label+': '+val(f.properties,metric)}}
let view=[0,0,1000,650],dragStart=null,dragMoved=false;const map=el('map');
function setView(v){view=v;map.setAttribute('viewBox',v.join(' '))}
function zoom(factor,cx=view[0]+view[2]/2,cy=view[1]+view[3]/2){const w=Math.min(6000,Math.max(5,view[2]*factor)),r=w/view[2];setView([cx-(cx-view[0])*r,cy-(cy-view[1])*r,w,view[3]*r])}
function svgPoint(event){const p=map.createSVGPoint();p.x=event.clientX;p.y=event.clientY;return p.matrixTransform(map.getScreenCTM().inverse())}
map.addEventListener('wheel',e=>{e.preventDefault();const p=svgPoint(e);zoom(e.deltaY>0?1.15:1/1.15,p.x,p.y)},{passive:false});
map.addEventListener('pointerdown',e=>{if(e.button!==0)return;dragMoved=false;dragStart={x:e.clientX,y:e.clientY,view:[...view],matrix:map.getScreenCTM().inverse()};map.classList.add('dragging')});
window.addEventListener('pointermove',e=>{if(!dragStart)return;const dx=e.clientX-dragStart.x,dy=e.clientY-dragStart.y;if(Math.hypot(dx,dy)>4)dragMoved=true;const m=dragStart.matrix;setView([dragStart.view[0]-(dx*m.a+dy*m.c),dragStart.view[1]-(dx*m.b+dy*m.d),dragStart.view[2],dragStart.view[3]])});
window.addEventListener('pointerup',()=>{dragStart=null;map.classList.remove('dragging')});
el('zoomIn').onclick=()=>zoom(1/1.5);el('zoomOut').onclick=()=>zoom(1.5);el('resetMap').onclick=()=>setView([0,0,1000,650]);
function selectBlock(id,focus=false){selected=id;const entry=mapPaths.get(id);if(!entry)return;const p=entry.feature.properties;el('detail').replaceChildren(node('h3','Квартал '+id));const dl=node('dl');
for(const m of metrics){dl.append(node('dt',m.label),node('dd',val(p,m)+(m.unit&&num(p[m.key])!==null?' '+m.unit:'')))}
dl.append(node('dt','Модельное население'),node('dd',fmt(num(p.population),0)));el('detail').append(dl,node('small','Типы и оценки зависят от полноты OSM. Нет значения ≠ нулевое значение.'));
if(focus){const b=entry.path.getBBox(),w=Math.max(35,b.width*1.6),h=Math.max(23,b.height*1.6),ratio=1000/650;const width=Math.max(w,h*ratio);setView([b.x+b.width/2-width/2,b.y+b.height/2-width/ratio/2,width,width/ratio])}drawMap();drawTable()}
function distribution(){const rows=filtered();let bins=[],missing=0;if(metric.kind==='category'){const counts=new Map();for(const f of rows){const v=f.properties[metric.key];if(v===null||v===undefined||v===''){missing++;continue}counts.set(v,(counts.get(v)||0)+1)}bins=[...counts].sort((a,b)=>b[1]-a[1]).map(([v,n])=>[typeText(v),n,colorFor(v)])}
else{const values=rows.map(f=>num(f.properties[metric.key])).filter(v=>v!==null);missing=rows.length-values.length;if(values.length){const lo=Math.min(...values),hi=Math.max(...values);if(lo===hi)bins=[[fmt(lo,3),values.length,colorFor(lo)]];else{bins=Array.from({length:8},(_,i)=>{const a=lo+(hi-lo)*i/8,b=lo+(hi-lo)*(i+1)/8;return[fmt(a,2)+' – '+fmt(b,2),0,colorFor((a+b)/2)]});values.forEach(v=>bins[Math.min(7,Math.floor((v-lo)/(hi-lo)*8))][1]++)}}}
el('chartCaption').textContent=metric.label+' · число кварталов в каждой группе';el('distribution').replaceChildren();const peak=Math.max(1,...bins.map(b=>b[1]));for(const [label,n,color]of bins){const r=node('div',undefined,'bar-row'),t=node('span',label),track=node('div',undefined,'bar-track'),fill=node('div',undefined,'bar-fill');t.title=label;fill.style.width=(n/peak*100)+'%';fill.style.background=color;track.append(fill);r.append(t,track,node('span',fmt(n,0)));el('distribution').append(r)}if(!bins.length)el('distribution').append(node('p','Для выбранного показателя нет сохранённых значений.','muted'));el('chartMissing').textContent='Показано кварталов: '+rows.length+'. Без значения: '+missing+'. Распределение не является новым расчётом показателя.'}
const tableColumns=[{key:'block_id',label:'Квартал',kind:'number'},...metrics];
function drawTable(){const table=el('metricsTable');table.tHead.replaceChildren();const tr=node('tr');for(const m of tableColumns){const th=node('th'),b=node('button',m.label+(sortKey===m.key?(sortAsc?' ↑':' ↓'):''));b.type='button';b.onclick=()=>{sortAsc=sortKey===m.key?!sortAsc:true;sortKey=m.key;drawTable()};th.setAttribute('aria-sort',sortKey===m.key?(sortAsc?'ascending':'descending'):'none');th.append(b);tr.append(th)}table.tHead.append(tr);const search=el('search').value.trim();let rows=filtered().filter(f=>!search||String(f.properties.block_id).includes(search));const m=tableColumns.find(x=>x.key===sortKey);rows.sort((a,b)=>{let x=a.properties[sortKey],y=b.properties[sortKey];if(m.kind==='number'){x=num(x);y=num(y)}if(x===null||x===undefined)return y===null||y===undefined?0:1;if(y===null||y===undefined)return-1;const cmp=typeof x==='number'?x-y:String(x).localeCompare(String(y),'ru');return sortAsc?cmp:-cmp});table.tBodies[0].replaceChildren();for(const f of rows){const tr=node('tr');if(f.properties.block_id===selected)tr.classList.add('active');for(const c of tableColumns){const td=node('td');if(c.key==='block_id'){const b=node('button',String(f.properties.block_id),'row-link');b.type='button';b.onclick=()=>selectBlock(f.properties.block_id,true);td.append(b)}else{td.textContent=val(f.properties,c);if(td.textContent==='Нет данных')td.classList.add('missing')}tr.append(td)}table.tBodies[0].append(tr)}el('rowCount').textContent='Строк: '+rows.length+' из '+features.length}
function refresh(){updateScale();drawMap();distribution();drawTable()}
el('metric').onchange=()=>{metric=metrics.find(m=>m.key===el('metric').value);refresh()};el('landFilter').onchange=refresh;el('search').oninput=drawTable;
const factLabels={floors_estimated_buildings:'Зданий с подставленной этажностью',residential_unknown_buildings:'Зданий с неизвестным жилым назначением',undefined_density_blocks:'Кварталов с неопределёнными коэффициентами',footprint_exceeds_site_blocks:'Кварталов, где пятна превышают площадь территории',unassigned_buildings:'Зданий вне кварталов',school_capacity_estimated_count:'Школ с подставленной вместимостью',unassigned_schools:'Школ вне кварталов'};
for(const [key,label]of Object.entries(factLabels))addFact(el('qualityFacts'),label+': '+fmt(report[key],0)+'.');
addFact(el('qualityFacts'),'Модельное население: '+fmt(report.estimated_population_in_blocks,0)+'. Не фактическая численность жителей Кореновска.');
const limits=DATA.limitations;if(limits){addFact(el('cuttingFacts'),'Кварталов в диагностике: '+fmt(limits.blocks_count,0)+'.');addFact(el('cuttingFacts'),'Потенциальных артефактов у ЖД: '+fmt(limits.potential_rail_artifacts_count,0)+'. Это кандидаты на проверку, не доказанные ошибки.');addFact(el('cuttingFacts'),'Крупных кварталов более 10 га: '+fmt(limits.large_blocks_over_10ha_count,0)+'. Большой размер не обязательно является ошибкой.');if(limits.geometry_valid===true)addFact(el('cuttingFacts'),'По сообщённой диагностике геометрия валидна.');if(limits.overlapping_pairs===0)addFact(el('cuttingFacts'),'По сообщённой диагностике перекрытий нет.');addFact(el('cuttingFacts'),'Ручная корректировка не выполнялась. Узкие фрагменты и крупные кварталы ограничивают сопоставимость показателей.');addFact(el('cuttingFacts'),'Происхождение сводки: '+DATA.limitationsSource+'.');if(DATA.limitationsMatch===false)addFact(el('cuttingFacts'),'ВНИМАНИЕ: контрольная сумма кварталов отличается от диагностированного варианта. Ограничения относятся к прежнему файлу.')}else addFact(el('cuttingFacts'),'Сводка диагностики не найдена в отчёте или метаданных ноутбука. Числа не подставлены.');
const assumptions=report.assumptions||{};el('assumptions').append(node('p','Учебные допущения: этажность при пропуске — '+fmt(assumptions.default_floors,0)+'; коэффициент жилой площади — '+fmt(assumptions.living_area_coefficient)+'; жилая площадь на человека — '+fmt(assumptions.living_demand_m2)+' м². Признаки жилого здания определялись по тегам OSM.'));
for(const [k,v]of Object.entries(report)){const tr=node('tr');tr.append(node('td',k),node('td',typeof v==='object'&&v!==null?JSON.stringify(v):fmt(v)));el('reportTable').append(tr)}
for(const message of DATA.warnings)addFact(el('qualityFacts'),message);
const conclusions=[
 'Исследование описывает сохранённую автоматическую нарезку '+features.length+' кварталов города. Изменение границ аналитических единиц способно изменить агрегированные характеристики.',
 'Карты FSI и GSI показывают распределение сохранённых характеристик застройки. MXI, средняя этажность и морфотипы дополнительно зависят от допущений о назначении и этажности зданий.',
 'Оценка '+fmt(report.estimated_population_in_blocks,0)+' жителей относится к учебной модели по распознанной жилой площади. Неполное жилое назначение OSM не позволяет считать её населением города или надёжно судить о расселении.',
 'Расположение и модельная вместимость школ представлены по сохранённым данным. Без проверенной численности жителей и фактической вместимости вывод о реальном дефиците мест необоснован.',
 'Готовый транспортный граф отсутствует. Время в пути, конкурентная обеспеченность школами и area_accessibility не рассчитаны; соответствующая часть задания остаётся незавершённой.',
 'Для более надёжных выводов нужны проверка этажности и жилого назначения, уточнение вместимости школ, оценка артефактов нарезки и получение совместимого готового транспортного графа.'
];conclusions.forEach(t=>addFact(el('conclusions'),t));
for(const fig of DATA.figures){const f=node('figure'),img=node('img');img.src=fig.data;img.alt=fig.caption;img.loading='lazy';f.append(img,node('figcaption',fig.caption));el('savedFigures').append(f)}
if(!DATA.figures.length)el('savedFigures').append(node('p','Сохранённые PNG не найдены. Карта, распределения и таблица доступны.','muted'));
const links=[['csvDownload',DATA.csv,'text/csv;charset=utf-8'],['geoDownload',DATA.originalGeojson,'application/geo+json']];
for(const [id,value,type]of links){const a=el(id);a.href=URL.createObjectURL(new Blob([value],{type}))}
refresh();
</script></body></html>
'''


def read_json(path: Path) -> dict:
    """Прочитать сохранённый JSON без изменения исходного файла."""
    def reject_constant(value: str):
        raise ValueError(f"{path.name}: недопустимое JSON-значение {value}; ожидается null")

    return json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=reject_constant)


def normalized(value):
    """Привести CSV-ячейку к типу значения, не вычисляя показатели."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        if value.lower() in ("true", "false"):
            return value.lower() == "true"
        try:
            number = float(value)
        except ValueError:
            return value
        if not math.isfinite(number):
            return None
        return number
    return value


def same_value(left, right) -> bool:
    left, right = normalized(left), normalized(right)
    if isinstance(left, (float, int)) and isinstance(right, (float, int)):
        return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9)
    return left == right


def load_payload(results: Path, notebook: Path) -> dict:
    """Прочитать готовые таблицы, геометрию, отчёт и PNG; проверить согласованность."""
    required = [results / name for name in
                ("blocks_indicators.geojson", "blocks_indicators.csv", "quality_report.json")]
    for path in required:
        if not path.is_file():
            raise ValueError(f"Не найден {path}. Сначала самостоятельно завершите раздел 12 ноутбука.")
    geo_path, csv_path, report_path = required
    original_geojson = geo_path.read_text(encoding="utf-8-sig")
    geojson = read_json(geo_path)
    report = read_json(report_path)
    if geojson.get("type") != "FeatureCollection" or not geojson.get("features"):
        raise ValueError("blocks_indicators.geojson должен содержать непустой FeatureCollection")
    if report.get("network_calculated") is not False:
        raise ValueError("Этот дашборд предназначен для этапа без графа. Статус network_calculated должен быть false.")
    if report.get("population_is_official") is not False:
        raise ValueError("Ожидалась модельная, а не официальная оценка населения. Проверьте отчёт.")
    csv_text = csv_path.read_text(encoding="utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    by_id = {}
    for row in rows:
        key = str(int(row["block_id"]))
        if key in by_id:
            raise ValueError(f"Повторяющийся block_id в CSV: {key}")
        by_id[key] = row
    feature_ids = set()
    for feature in geojson["features"]:
        props = feature.get("properties") or {}
        if "block_id" not in props:
            raise ValueError("В GeoJSON отсутствует block_id")
        key = str(int(props["block_id"]))
        if key in feature_ids or key not in by_id:
            raise ValueError(f"Несогласованные или повторяющиеся block_id: {key}")
        feature_ids.add(key)
        props["block_id"] = int(key)
        for name, value in by_id[key].items():
            if name in props and not same_value(props[name], value):
                raise ValueError(f"CSV и GeoJSON расходятся: квартал {key}, поле {name}. Не смешивайте разные запуски.")
            if name not in props:
                props[name] = normalized(value)
        geometry = feature.get("geometry") or {}
        if geometry.get("type") not in ("Polygon", "MultiPolygon") or not geometry.get("coordinates"):
            raise ValueError(f"Квартал {key}: ожидается Polygon или MultiPolygon")
        feature["properties"] = props
    if len(feature_ids) != len(by_id):
        raise ValueError("Наборы кварталов в CSV и GeoJSON отличаются")
    if report.get("blocks") != len(feature_ids):
        raise ValueError("Число кварталов в quality_report.json не совпадает с GeoJSON")
    warnings = []
    if len(feature_ids) != 403:
        warnings.append(f"В файле {len(feature_ids)} кварталов, тогда как согласованный вариант содержал 403.")
    keys = {name for f in geojson["features"] for name in f["properties"]}
    for metric in METRICS:
        if metric["key"] not in keys:
            warnings.append(f"Показатель «{metric['label']}» отсутствует в сохранённых файлах.")
    limitations = report.get("automatic_cutting_limitations")
    limitations_source = "quality_report.json"
    if not limitations and notebook.is_file():
        metadata = read_json(notebook).get("metadata", {}).get("korenovsk_research", {})
        limitations = metadata.get("automatic_cutting_limitations")
        limitations_source = "метаданные ноутбука; результаты диагностики сообщены пользователем"
    limitations_match = None
    blocks_path = results.parent / "processed" / "blocks.geojson"
    if limitations and limitations.get("blocks_sha256") and blocks_path.is_file():
        limitations_match = hashlib.sha256(blocks_path.read_bytes()).hexdigest() == limitations["blocks_sha256"]
    figure_names = {
        "population_density_per_ha.png": "Модельная плотность населения: карта и распределение",
        "fsi.png": "FSI: карта и распределение сохранённых значений",
        "gsi.png": "GSI: карта и распределение сохранённых значений",
        "spacematrix_morphotype.png": "Модельные морфотипы Spacematrix",
        "strelka_morphotype.png": "Модельные морфотипы «Стрелки»",
    }
    figures = []
    for name, caption in figure_names.items():
        path = results / name
        if path.is_file():
            figures.append({"caption": caption, "data": "data:image/png;base64," +
                            base64.b64encode(path.read_bytes()).decode("ascii")})
    return {"geojson": geojson, "originalGeojson": original_geojson, "csv": "\ufeff" + csv_text,
            "report": report, "metrics": METRICS, "limitations": limitations,
            "limitationsSource": limitations_source, "limitationsMatch": limitations_match,
            "figures": figures, "warnings": warnings,
            "generated": datetime.now().astimezone().isoformat(timespec="seconds")}


def main() -> None:
    """Записать единственную HTML-страницу только при явном запуске пользователем."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS, help="Папка сохранённых результатов")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Путь итогового dashboard.html")
    parser.add_argument("--notebook", type=Path, default=ROOT / "examples" / "korenovsk_research.ipynb",
                        help="Ноутбук с сохранёнными ограничениями диагностики")
    args = parser.parse_args()
    try:
        results = args.results.resolve()
        output = args.output.resolve()
        if output.suffix.lower() != ".html":
            raise ValueError("Итоговый файл должен иметь расширение .html")
        if results == output or results in output.parents:
            raise ValueError("Сохраните HTML вне папки исходных результатов, например в корне проекта")
        if not output.parent.is_dir():
            raise ValueError("Папка для HTML не существует. Укажите существующую папку через --output")
        payload = load_payload(results, args.notebook.resolve())
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        # Защита от завершения script-тега значением из OSM и от внедрения разметки.
        encoded = encoded.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
        output.write_text(HTML.replace("__DASHBOARD_DATA__", encoded), encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"Не удалось создать дашборд: {exc}\n")
    print(f"Создан {output}")
    print("Страница работает без интернета. Откройте dashboard.html в браузере.")
    print("Показатели прочитаны из сохранённых файлов; транспортные показатели отмечены как недоступные.")


if __name__ == "__main__":
    main()
