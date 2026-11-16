"""Собрать самостоятельный HTML-дашборд из проверенных результатов Обнинска."""

import json
import html as html_module
import os
from pathlib import Path

DATA = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(DATA / "cache/matplotlib"))

import geopandas as gpd

from visuals import METRICS, TRANSLATIONS, translate


def generate_dashboard(data: Path = DATA) -> Path:
    """Создать HTML с картой, графиками и таблицей всех обязательных показателей."""
    blocks = gpd.read_file(data / "blocks_results.geojson").to_crs(4326)
    schools = gpd.read_file(data / "schools.geojson").to_crs(4326)
    translations = dict(TRANSLATIONS)
    for column in ["land_use", "spacematrix", "strelka"]:
        translations.update({value: translate(value) for value in blocks[column].dropna().unique()})
    payload = {"blocks": json.loads(blocks.to_json()), "schools": json.loads(schools.to_json()),
               "metrics": METRICS, "translations": translations,
               "summary": json.loads((data / "summary.json").read_text())}
    scenarios = json.loads((data / "population_scenarios.json").read_text())
    comparison = '<section class="card notes" style="margin-bottom:16px"><h2>Проверка населения: до и после</h2><table><tr><th>Вариант</th><th>Жителей</th></tr>'
    comparison += ''.join('<tr><td>' + html_module.escape(row['Вариант']) + '</td><td>' + f"{row['Население']:,}".replace(',', ' ') + '</td></tr>' for row in scenarios)
    comparison += '</table><p>Равенство 133 тыс. — результат условной калибровки. Исходная оценка сохранена; население кварталов остаётся модельным.</p></section>'
    html = TEMPLATE.replace('__COMPARISON__', comparison).replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"))
    target = data / "dashboard.html"
    target.write_text(html)
    print(target)
    return target


TEMPLATE = r'''<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Обнинск · кварталы и школы</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
:root{font-family:system-ui,-apple-system,sans-serif;color:#142c40;background:#f3f5f7}*{box-sizing:border-box}
body{margin:0}header{background:#14364a;color:white;padding:28px 4vw}header small{color:#a5cdd9;letter-spacing:2px}
h1{font-size:32px;margin:8px 0}header p{max-width:950px;color:#d1e5ec;font-size:14px}.wrap{padding:22px 4vw}
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:20px}.card{background:white;border:1px solid #dce3e9;border-radius:12px;padding:16px}
.kpis b{display:block;font-size:27px;color:#106a75}.muted,small{color:#5e7180;font-size:12px}.grid{display:grid;grid-template-columns:2fr 1fr;gap:16px}
#map{height:650px;border-radius:10px;z-index:0}select,input,button{font:inherit;padding:9px;border:1px solid #cbd5e1;border-radius:6px;background:white}
select{width:100%;margin:8px 0}h2{font-size:18px;margin:4px 0 12px}h3{font-size:14px}.description{font-size:13px;line-height:1.55;min-height:58px}
#legend{background:#fff;padding:8px;font-size:11px;max-width:280px;max-height:280px;overflow:auto}.swatch{display:inline-block;width:13px;height:13px;vertical-align:middle;border:1px solid #64748b;margin:2px 5px 2px 0}
#stats{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;font-size:12px;margin:15px 0}#stats div{padding:8px;background:#f1f5f9;border-radius:6px}
.barrow{display:flex;align-items:center;font-size:11px;gap:6px;margin:5px 0}.barlabel{width:125px;flex-shrink:0;word-break:break-word}.bar{height:14px;background:#168b9c;min-width:1px}.barvalue{white-space:nowrap}
.tablewrap{overflow:auto;max-height:430px;margin-top:12px}table{width:100%;border-collapse:collapse;font-size:12px}th{position:sticky;top:0;background:#eaf0f4;cursor:pointer}td,th{padding:9px;text-align:left;border-bottom:1px solid #e2e8f0}tbody tr{cursor:pointer}tbody tr:hover{background:#e0f2fe}
.notes{line-height:1.6;font-size:13px;margin-top:16px}.notes strong{color:#8a4b12}.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.toolbar input{width:190px}a{color:#076c87}
@media(max-width:900px){.grid{grid-template-columns:1fr}.kpis{grid-template-columns:repeat(2,1fr)}#map{height:500px}}
</style></head><body><header><small>ПРАКТИЧЕСКАЯ РАБОТА № 2 · BLOCKSNET</small><h1>Обнинск: кварталы, застройка и школы</h1>
<p>298 согласованных кварталов · территория 43,84 км² · пешеходная сеть OSM · 4,5 км/ч.<br>
Учебная модель. Население и часть школьных мощностей оценены; результаты не являются официальной статистикой.</p></header>
<main class="wrap"><div class="kpis" id="kpis"></div>__COMPARISON__<div class="grid"><section class="card"><div id="map"></div></section>
<aside class="card"><h2>Показатель на карте</h2><select id="metric" aria-label="Выбор показателя"></select>
<p id="description" class="description"></p><div id="stats"></div><h3>Распределение по кварталам</h3><div id="hist"></div>
<h3>Кварталы с наибольшим неудовлетворённым спросом</h3><div id="priority"></div><p class="muted">Приоритет — результат исходной модели, без размещения новых школ.</p></aside></div>
<section class="card" style="margin-top:16px"><div class="toolbar"><h2 style="margin-right:auto">Таблица кварталов</h2>
<input id="search" placeholder="Номер квартала" aria-label="Поиск квартала"><button id="export">Скачать таблицу CSV</button></div>
<p class="muted">Нажмите на заголовок для сортировки, на строку — для перехода к кварталу. «Нет данных» отличается от нуля.</p>
<div class="tablewrap"><table><thead><tr><th data-sort="block_id">ID ↕</th><th data-sort="population">Население ↕</th>
<th data-sort="capacity">Мест ↕</th><th data-sort="unmet_demand">Неудовлетворённый спрос ↕</th><th id="metricHeader">Показатель ↕</th></tr></thead><tbody id="rows"></tbody></table></div></section>
<section class="card notes"><h2>Как читать результаты</h2>
<p><strong>Население.</strong> Первоначальная оценка 198 871 сохранена для сравнения. Садовые дома давали только 1087 жителей (0,55%).
Проверены крупнейшие кварталы, уточнены аналоги этажности, ТЦ «Самсон» исключён из жилья.
В OSM город и городской округ имеют одинаковые контуры. Это основание для <strong>условной учебной калибровки к округлённым 133 тыс. жителей на 01.01.2025</strong>.
Итог распределён по уточнённой жилой площади вне садовых зон, с целочисленным округлением; площадь территории не используется как вес.
Нулевая постоянная заселённость садов — сценарное допущение; фактическая регистрация неизвестна.
Совпадение общей численности с ориентиром не подтверждает точность её распределения. Юридический контур не проверен;
расхождение с площадью 55,03 км² из другого документа и разница дат статистики/OSM остаются ограничениями.
Население кварталов и школьный дефицит — модельные, а не официальные показатели.</p>
<p><strong>Школы.</strong> Каталог различает организации и площадки. Общий корпус СОШ №18 и ФТШ учтён один раз;
«№19» в OSM сопоставлена со вторым корпусом №18 «Время, вперёд!». Для части школ мощность опубликована, для остальных — модель площади / 18 м² на место.
В основную общедоступную мощность включены 19 муниципальных площадок. Частные школы, спортивная школа с отбором и компенсирующая начальная школа №35 показаны серым и не покрывают неограниченный спрос.
Это консервативное допущение. Из 25 записей каталога размещения мощность опубликована для трёх корпусов; вместимость остальных требует уточнения. Части общих зданий не являются самостоятельными мощностями.</p>
<p><strong>Доступность.</strong> Сетевые минуты между ближайшими узлами основной связной компоненты; подходы от внутренней точки квартала к узлу не добавлены.
Слой «Привязка квартала к сети» показывает эту погрешность. Крупные кварталы обобщают внутриквартальные различия.
Готовый граф не найден в проверенных источниках: OSMnx построил пешеходный граф из локальной выгрузки. Это отступление от требования использовать готовый граф.</p>
<p><strong>Обеспеченность.</strong> BlocksNet competitive_provision, спрос 120 мест/1000 жителей, порог 15 минут, self_supply=True, max_depth=1.
Нулевой спрос даёт «нет данных» для доли обеспеченности. area_accessibility — среднее время до территории с весами по площади, меньше — лучше.
Для практики №3 сохранены матрица 298×298, согласованные ID, население, мощности, параметры и исходный спрос. Новые школы пока не моделировались.</p>
<p>Источники: <a href="https://www.openstreetmap.org/relation/3396088">OpenStreetMap · ODbL</a>,
<a href="https://obninsk.ru/obninsk/economic-development/stat/">статистика администрации</a>,
<a href="https://www.obninsk.ru/obninsk/social-sphere/education/Obninskschools/">каталог школ</a>,
<a href="https://mvin8.github.io/ai-technologies-in-urbanism/content/practice/practice-02.html">задание</a>.
Подложка и Leaflet требуют интернет; геометрия, показатели и графики встроены в этот HTML.</p></section></main>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>
const D=__PAYLOAD__, features=D.blocks.features, fmt=(x)=>x==null?'Нет данных':typeof x==='number'?x.toLocaleString('ru-RU',{maximumFractionDigits:3}):D.translations[x]||x;
const esc=x=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const s=D.summary;
document.getElementById('kpis').innerHTML=[['Кварталов',s.blocks],['Население · модель',s.population_model],['Мест · модель',s.capacity_baseline],['Обеспеченность',s.provision_percent+'%'],['Неудовлетворённый спрос',s.unmet_demand]].map(([t,v])=>`<div class="card"><small>${t}</small><b>${fmt(v)}</b></div>`).join('');
const select=document.getElementById('metric');Object.entries(D.metrics).forEach(([key,m])=>select.add(new Option(m.title,key)));select.value='provision_strong';
const map=L.map('map');L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap contributors',maxZoom:19}).addTo(map);
let layer, selected=null, sortKey='unmet_demand',descending=true;
const schoolLayer=L.layerGroup();D.schools.features.forEach(f=>{let p=f.properties,c=f.geometry.coordinates;
L.circleMarker([c[1],c[0]],{radius:5,color:p.public_supply?'#14532d':'#64748b',fillOpacity:.9,weight:2})
.bindPopup(`<b>${esc(p.name)}</b><br>${fmt(p.capacity)} мест<br>${esc(p.capacity_source)}<br>${p.public_supply?'В основной мощности':'Вне общедоступной мощности'}`).addTo(schoolLayer)});schoolLayer.addTo(map);
L.control.layers(null,{'Школьные площадки':schoolLayer}).addTo(map);
const legend=L.control({position:'bottomleft'});legend.onAdd=()=>{const e=L.DomUtil.create('div');e.id='legend';return e};legend.addTo(map);
function bars(target,items){let max=Math.max(1,...items.map(x=>x[1]));document.getElementById(target).innerHTML=items.map(([label,v])=>`<div class="barrow"><span class="barlabel">${esc(label)}</span><span class="bar" style="width:${v/max*42}%"></span><span class="barvalue">${fmt(v)}</span></div>`).join('')}
bars('priority',features.filter(f=>f.properties.unmet_demand>0).sort((a,b)=>b.properties.unmet_demand-a.properties.unmet_demand).slice(0,8).map(f=>['Квартал '+f.properties.block_id,f.properties.unmet_demand]));
function table(){let k=select.value,q=document.getElementById('search').value.trim();let rows=features.filter(f=>!q||String(f.properties.block_id).includes(q)).sort((a,b)=>{
let x=a.properties[sortKey],y=b.properties[sortKey];if(x==null)return 1;if(y==null)return -1;let v=typeof x==='number'?x-y:String(x).localeCompare(String(y),'ru');return descending?-v:v});
document.getElementById('metricHeader').textContent=D.metrics[k].title+' ↕';document.getElementById('rows').innerHTML=rows.map(f=>{let p=f.properties;return `<tr data-id="${p.block_id}"><td>${p.block_id}</td><td>${fmt(p.population)}</td><td>${fmt(p.capacity)}</td><td>${fmt(p.unmet_demand)}</td><td>${esc(fmt(p[k]))}</td></tr>`}).join('');
document.querySelectorAll('#rows tr').forEach(tr=>tr.onclick=()=>{layer.eachLayer(l=>{if(String(l.feature.properties.block_id)===tr.dataset.id){map.fitBounds(l.getBounds(),{maxZoom:16});l.openPopup()}})})}
function update(){const k=select.value,vals=features.map(f=>f.properties[k]),valid=vals.filter(v=>v!=null),numeric=valid.some(v=>typeof v==='number');
document.getElementById('description').textContent=D.metrics[k].description;
let sorted=[...valid].sort((a,b)=>a-b),max=numeric?Math.max(1,...valid):1,cats=numeric?[]:[...new Set(valid)].sort();
const palette=['#2563eb','#16a34a','#d97706','#dc2626','#9333ea','#0891b2','#db2777','#4d7c0f','#6d28d9','#78716c','#0f766e','#e11d48','#7c3aed','#92400e'];
function color(v){if(v==null)return '#b8bec7';if(!numeric)return palette[cats.indexOf(v)%palette.length];if(v===0)return '#ffffff';
if(k==='provision_strong')return `hsl(${v*120},65%,${65-v*20}%)`;return `hsl(195,70%,${92-60*Math.sqrt(Math.max(0,v)/max)}%)`}
if(layer)map.removeLayer(layer);layer=L.geoJSON(D.blocks,{style:f=>({color:'#334155',weight:.85,fillColor:color(f.properties[k]),fillOpacity:.78}),onEachFeature:(f,l)=>{
let p=f.properties;l.bindTooltip('Квартал '+p.block_id+' · '+esc(fmt(p[k])));l.bindPopup(`<b>Квартал ${p.block_id}</b><br>${esc(D.metrics[k].title)}: ${esc(fmt(p[k]))}<br>Население: ${fmt(p.population)}<br>Мест: ${fmt(p.capacity)}`);
l.on('mouseover',()=>l.setStyle({weight:3}));l.on('mouseout',()=>layer.resetStyle(l))}}).addTo(map);schoolLayer.eachLayer(marker=>marker.bringToFront());
if(!selected){map.fitBounds(layer.getBounds());selected=true}
document.getElementById('legend').innerHTML='<b>'+esc(D.metrics[k].title)+'</b><br>'+(!numeric?cats.map(c=>`<span class="swatch" style="background:${color(c)}"></span>${esc(fmt(c))}<br>`).join(''):`<span class="swatch" style="background:${color(max/2)}"></span>Цвет: 0 → ${fmt(max)}<br><span class="swatch" style="background:white"></span>Ноль<br>`)+
'<span class="swatch" style="background:#b8bec7"></span>Нет данных / без застройки';
let stats=[['Кварталов',features.length],['Нет данных',vals.length-valid.length]];
if(numeric){let mid=sorted.length>>1,median=sorted.length?(sorted.length%2?sorted[mid]:(sorted[mid-1]+sorted[mid])/2):null;stats.push(['Ноль',valid.filter(v=>v===0).length],['Медиана',median],['Минимум',sorted[0]],['Максимум',sorted.at(-1)])}
document.getElementById('stats').innerHTML=stats.map(([t,v])=>`<div>${t}<br><b>${fmt(v)}</b></div>`).join('');
if(numeric){let bins=Array(8).fill(0);valid.forEach(v=>bins[Math.min(7,Math.floor(v/max*8))]++);bars('hist',bins.map((v,i)=>[`${fmt(i*max/8)}–${fmt((i+1)*max/8)}`,v]))}
else{bars('hist',cats.map(c=>[fmt(c),valid.filter(v=>v===c).length]))}table()}
select.onchange=update;document.getElementById('search').oninput=table;
document.querySelectorAll('th[data-sort]').forEach(th=>th.onclick=()=>{sortKey=th.dataset.sort;descending=!descending;table()});
document.getElementById('metricHeader').onclick=()=>{sortKey=select.value;descending=!descending;table()};
document.getElementById('export').onclick=()=>{const cols=['block_id','population','capacity','unmet_demand',select.value];
let text='\ufeff'+cols.join(';')+'\n'+features.map(f=>cols.map(c=>JSON.stringify(f.properties[c]??'')).join(';')).join('\n');
let a=document.createElement('a');a.href=URL.createObjectURL(new Blob([text],{type:'text/csv;charset=utf-8'}));a.download='obninsk_blocks.csv';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};update();
</script></body></html>'''


if __name__ == "__main__":
    generate_dashboard()
