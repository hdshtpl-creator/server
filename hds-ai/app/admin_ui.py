"""admin_ui.py — Giao diện web quản trị (một trang). Tách khỏi api.py cho gọn."""

ADMIN_HTML = """<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HDS AI — Quản trị</title><style>
:root{--navy:#1f3864;--blue:#2e74b5;--soft:#f2f6fb;--red:#c00000;--green:#2e7d32}
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;margin:0;background:#eef2f7;color:#222}
header{background:var(--navy);color:#fff;padding:14px 20px;display:flex;align-items:center;gap:16px}
header h1{font-size:18px;margin:0;font-weight:600}
header input{width:60px;padding:5px;border:0;border-radius:5px}
nav{display:flex;gap:4px;background:#fff;padding:8px 20px;border-bottom:1px solid #dde;flex-wrap:wrap}
nav button{padding:8px 14px;border:0;background:#eef2f7;border-radius:6px;cursor:pointer;font-size:14px}
nav button.active{background:var(--blue);color:#fff}
main{padding:20px;max-width:1150px;margin:0 auto}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:20px}
.stat{background:#fff;border:1px solid #dde;border-radius:10px;padding:16px}
.stat .n{font-size:28px;font-weight:700;color:var(--navy)}
.stat .l{font-size:13px;color:#667;margin-top:4px}
.stat.alert .n{color:var(--red)}
.card{background:#fff;border:1px solid #dde;border-radius:8px;padding:14px;margin:12px 0}
.meta{color:#667;font-size:13px;margin-bottom:6px}
.q{font-weight:600;color:var(--navy)}
.a{white-space:pre-wrap;background:var(--soft);padding:10px;border-radius:6px;font-size:14px;margin:8px 0}
button.act{padding:7px 13px;margin-right:6px;border:0;border-radius:6px;cursor:pointer;font-size:14px;color:#fff}
.ok{background:var(--green)} .edit{background:#f9a825;color:#222} .no{background:var(--red)}
select,input.f,textarea{padding:6px;margin:3px 3px 3px 0;border:1px solid #ccd;border-radius:5px;font-family:inherit}
textarea{width:100%;min-height:90px}
table{width:100%;border-collapse:collapse;font-size:14px;background:#fff}
th,td{border:1px solid #dde;padding:8px;text-align:left}
th{background:var(--navy);color:#fff}
.warn{background:#fff3cd;border-left:4px solid #f9a825;padding:10px;margin:10px 0;border-radius:4px}
.hidden{display:none}
h2{color:var(--navy);font-size:20px}
</style></head><body>
<header>
  <h1>HDS AI — Bảng quản trị</h1>
  <span id="whoami" style="font-size:13px"></span>
  <button onclick="logout()" style="padding:6px 12px;border:0;border-radius:5px;cursor:pointer;margin-left:auto">Đăng xuất</button>
</header>
<div id="loginBox" style="max-width:340px;margin:80px auto;background:#fff;padding:24px;border-radius:10px;border:1px solid #dde">
  <h2 style="margin-top:0;color:#1f3864">Đăng nhập</h2>
  <input class="f" id="li_email" placeholder="Email" style="width:100%;margin-bottom:8px">
  <input class="f" id="li_pw" type="password" placeholder="Mật khẩu" style="width:100%;margin-bottom:12px" onkeydown="if(event.key==='Enter')doLogin()">
  <button class="act ok" style="width:100%" onclick="doLogin()">Đăng nhập</button>
  <p id="li_err" style="color:#c00000;font-size:13px;margin:8px 0 0"></p>
</div>
<nav id="mainNav" class="hidden">
  <button class="active" onclick="tab('dash',this)">Tổng quan</button>
  <button onclick="tab('review',this)">Duyệt tài liệu</button>
  <button onclick="tab('learn',this)">Duyệt hội thoại</button>
  <button onclick="tab('docs',this)">Tài liệu đã học</button>
  <button onclick="tab('methods',this)">Mẫu phương pháp</button>
  <button onclick="tab('clients',this)">Hồ sơ khách 360°</button>
  <button onclick="tab('users',this)">Người dùng</button>
</nav>
<main id="mainArea" class="hidden">
  <div class="warn">Chỉ admin hoặc người được cấp quyền duyệt mới thao tác được. Con số "Thiếu chủ sở hữu" phải luôn bằng 0.</div>

  <section id="dash"><h2>Tổng quan</h2><div class="grid" id="stats"></div></section>

  <section id="review" class="hidden"><h2>Tài liệu chờ duyệt nhãn</h2><div id="reviewList"></div></section>

  <section id="learn" class="hidden"><h2>Hội thoại chờ duyệt (tự học)</h2><div id="learnList"></div></section>

  <section id="docs" class="hidden">
    <h2>Tài liệu AI đã học</h2>
    <div class="card">
      <input class="f" id="docq" placeholder="Tìm theo tên hoặc nội dung..." style="width:40%">
      <select id="doctype">
        <option value="">Tất cả loại</option>
        <option value="law">Văn bản luật</option>
        <option value="contract">Hợp đồng</option>
        <option value="advisory">Thư tư vấn</option>
        <option value="filing">Hồ sơ nộp</option>
        <option value="other">Khác</option>
      </select>
      <button class="act ok" onclick="loadDocs()">Tìm</button>
    </div>
    <div id="docList"></div>
  </section>

  <section id="methods" class="hidden">
    <h2>Dạy AI cách phân tích</h2>
    <div class="card">
      <input class="f" id="mtype" placeholder="Loại vụ việc (VD: Tranh chấp hợp đồng mua bán)" style="width:60%">
      <textarea id="msteps" placeholder="Quy trình phân tích, mỗi bước một dòng..."></textarea>
      <button class="act ok" onclick="addMethod()">Lưu mẫu phương pháp</button>
    </div>
    <div id="methodList"></div>
  </section>

  <section id="clients" class="hidden">
    <h2>Hồ sơ khách hàng 360°</h2>
    <div class="card">
      <select id="clientPick" onchange="loadDossier(this.value)"><option value="">— Chọn khách hàng —</option></select>
    </div>
    <div id="dossier"></div>
  </section>

  <section id="users" class="hidden">
    <h2>Người dùng</h2>
    <div class="card">
      <input class="f" id="uemail" placeholder="Email">
      <input class="f" id="uname" placeholder="Họ tên">
      <select id="urole">
        <option value="ban_qt">Ban Quản trị (thấy tất cả)</option>
        <option value="truong_bph">Trưởng bộ phận</option>
        <option value="chuyen_vien">Chuyên viên</option>
        <option value="tro_ly">Trợ lý</option>
        <option value="admin">Admin kỹ thuật</option>
      </select>
      <input class="f" id="udepts" placeholder="ID phòng, cách nhau dấu phẩy (VD: 1,3)" style="width:200px">
      <label><input type="checkbox" id="ucanrev"> Cấp quyền duyệt</label>
      <button class="act ok" onclick="addUser()">Tạo tài khoản</button>
    </div>
    <div id="userList"></div>
  </section>
</main>
<script>
let TOKEN = null;
const H = () => ({'Content-Type':'application/json','Authorization':'Bearer '+(TOKEN||'')});
async function doLogin(){
  const email=document.getElementById('li_email').value;
  const pw=document.getElementById('li_pw').value;
  const r=await fetch('/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({email,password:pw})});
  if(!r.ok){document.getElementById('li_err').textContent='Sai email hoặc mật khẩu';return;}
  const d=await r.json(); TOKEN=d.access_token;
  document.getElementById('loginBox').classList.add('hidden');
  document.getElementById('mainNav').classList.remove('hidden');
  document.getElementById('mainArea').classList.remove('hidden');
  document.getElementById('whoami').textContent=(d.user.full_name||d.user.role)+' ('+d.user.role+')';
  loadStats();
}
function logout(){ TOKEN=null;
  document.getElementById('loginBox').classList.remove('hidden');
  document.getElementById('mainNav').classList.add('hidden');
  document.getElementById('mainArea').classList.add('hidden');
  document.getElementById('whoami').textContent='';
}
function tab(id,btn){
  ['dash','review','learn','docs','methods','clients','users'].forEach(s=>document.getElementById(s).classList.add('hidden'));
  document.getElementById(id).classList.remove('hidden');
  document.querySelectorAll('nav button').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  if(id==='review')loadReview(); if(id==='learn')loadLearn();
  if(id==='docs')loadDocs();
  if(id==='methods')loadMethods(); if(id==='clients')loadClients(); if(id==='users')loadUsers();
}
async function loadStats(){
  const r=await fetch('/stats'); const s=await r.json();
  const items=[
    ['Tài liệu',s.tai_lieu,''],['Đã duyệt nhãn',s.da_duyet_nhan,''],
    ['Chờ duyệt nhãn',s.cho_duyet_nhan,''],['Thiếu chủ sở hữu',s.thieu_chu_so_huu,s.thieu_chu_so_huu>0?'alert':''],
    ['Số đoạn',s.so_doan,''],['Hội thoại chờ duyệt',s.hoi_thoai_cho_duyet,''],
    ['Đã học vào kho',s.da_hoc,''],['Mẫu phương pháp',s.so_mau_phuong_phap,'']
  ];
  document.getElementById('stats').innerHTML=items.map(([l,n,c])=>
    `<div class="stat ${c}"><div class="n">${n}</div><div class="l">${l}</div></div>`).join('');
}
async function loadReview(){
  const r=await fetch('/review/pending',{headers:H()});
  if(!r.ok){document.getElementById('reviewList').innerHTML='<p style="color:red">Lỗi '+r.status+' — kiểm tra quyền</p>';return;}
  const items=await r.json();
  document.getElementById('reviewList').innerHTML= items.length? items.map(x=>`
    <div class="card" id="rc${x.id}">
      <div class="meta">#${x.id} · nguồn: ${x.source_kind} · tin cậy ${x.confidence??'—'}</div>
      <div class="q">${x.title||'(không tiêu đề)'}</div>
      <div class="a">${(x.preview||'').slice(0,280)}...</div>
      Loại:<select id="t${x.id}">${['contract','advisory','filing','law','other'].map(v=>`<option ${v===x.doc_type?'selected':''}>${v}</option>`).join('')}</select>
      Quyền:<select id="a${x.id}">${['public','internal','client'].map(v=>`<option ${v===x.access_level?'selected':''}>${v}</option>`).join('')}</select>
      Khách ID:<input class="f" id="cl${x.id}" style="width:60px" value="${x.client_id??''}">
      <button class="act ok" onclick="approveDoc(${x.id})">Duyệt</button>
    </div>`).join('') : '<p>Không có tài liệu chờ duyệt.</p>';
}
async function approveDoc(id){
  const cl=document.getElementById('cl'+id).value;
  const r=await fetch(`/review/${id}/approve`,{method:'POST',headers:H(),body:JSON.stringify({
    doc_type:document.getElementById('t'+id).value,
    access_level:document.getElementById('a'+id).value,
    client_id:cl?parseInt(cl):null})});
  if(r.ok){document.getElementById('rc'+id).remove();loadStats();}else alert('Lỗi: '+(await r.text()));
}
async function loadLearn(){
  const r=await fetch('/learn/pending',{headers:H()});
  if(!r.ok){document.getElementById('learnList').innerHTML='<p style="color:red">Lỗi '+r.status+'</p>';return;}
  const items=await r.json();
  document.getElementById('learnList').innerHTML= items.length? items.map(x=>`
    <div class="card" id="lc${x.message_id}">
      <div class="meta">#${x.message_id} · ${x.created_at}</div>
      <div class="q">HỎI: ${x.question||'(không rõ)'}</div>
      <div class="a">${x.answer}</div>
      <textarea id="e${x.message_id}" placeholder="Sửa lại nếu cần..."></textarea>
      <button class="act ok" onclick="learn(${x.message_id},'approve')">Đạt</button>
      <button class="act edit" onclick="learn(${x.message_id},'edit')">Lưu bản sửa</button>
      <button class="act no" onclick="learn(${x.message_id},'reject')">Bỏ qua</button>
    </div>`).join('') : '<p>Không có hội thoại chờ duyệt.</p>';
}
async function learn(id,action){
  const ed=document.getElementById('e'+id).value;
  const r=await fetch(`/learn/${id}`,{method:'POST',headers:H(),body:JSON.stringify({
    action,edited_content:action==='edit'?ed:null,edit_reason:'other'})});
  if(r.ok){document.getElementById('lc'+id).remove();loadStats();}else alert('Lỗi: '+(await r.text()));
}
const TYPE_LABEL={law:'Luật',contract:'Hợp đồng',advisory:'Tư vấn',filing:'Hồ sơ',method:'Phương pháp',other:'Khác'};
const ACCESS_LABEL={public:'Công khai',internal:'Nội bộ',client:'Khách hàng'};
async function loadDocs(){
  const q=document.getElementById('docq').value;
  const t=document.getElementById('doctype').value;
  const r=await fetch(`/documents?q=${encodeURIComponent(q)}&doc_type=${t}`,{headers:H()});
  if(!r.ok){document.getElementById('docList').innerHTML='<p style="color:red">Lỗi '+r.status+' — chỉ admin/người được cấp quyền xem được</p>';return;}
  const items=await r.json();
  if(!items.length){document.getElementById('docList').innerHTML='<p>Chưa có tài liệu nào.</p>';return;}
  document.getElementById('docList').innerHTML=
    `<p style="color:#667;font-size:14px">Tổng ${items.length} tài liệu</p>`+
    `<table><tr><th>Tên tài liệu</th><th>Loại</th><th>Tóm tắt ý chính</th><th>Quyền</th><th>Đoạn</th><th>Ngày</th></tr>`+
    items.map(d=>`<tr>
      <td><b>${d.title||'(không tên)'}</b>${d.client_name?'<br><span style="color:#667;font-size:12px">'+d.client_name+'</span>':''}</td>
      <td>${TYPE_LABEL[d.doc_type]||d.doc_type||'—'}</td>
      <td style="font-size:13px">${d.summary}</td>
      <td>${ACCESS_LABEL[d.access_level]||d.access_level}</td>
      <td style="text-align:center">${d.so_doan}</td>
      <td style="white-space:nowrap">${d.created_at}</td>
    </tr>`).join('')+`</table>`;
}
async function loadMethods(){
  const r=await fetch('/methods',{headers:H()});
  if(!r.ok)return;
  const items=await r.json();
  document.getElementById('methodList').innerHTML=items.map(x=>`
    <div class="card"><div class="q">${x.case_type} ${x.approved?'✓':'(chờ)'}</div>
    <div class="a">${x.steps}</div></div>`).join('');
}
async function addMethod(){
  const r=await fetch('/methods',{method:'POST',headers:H(),body:JSON.stringify({
    case_type:document.getElementById('mtype').value,
    steps:document.getElementById('msteps').value})});
  if(r.ok){document.getElementById('mtype').value='';document.getElementById('msteps').value='';loadMethods();loadStats();}
  else alert('Lỗi: '+(await r.text()));
}
async function loadClients(){
  const r=await fetch('/clients',{headers:H()});
  if(!r.ok){document.getElementById('dossier').innerHTML='<p style="color:red">Lỗi '+r.status+'</p>';return;}
  const items=await r.json();
  document.getElementById('clientPick').innerHTML='<option value="">— Chọn khách hàng —</option>'+
    items.map(c=>`<option value="${c.id}">${c.name}${c.department?' ('+c.department+')':''}</option>`).join('');
}
async function loadDossier(cid){
  if(!cid){document.getElementById('dossier').innerHTML='';return;}
  const r=await fetch(`/clients/${cid}/360`,{headers:H()});
  if(!r.ok){document.getElementById('dossier').innerHTML='<p style="color:red">Lỗi '+r.status+' — '+(await r.text())+'</p>';return;}
  const d=await r.json();
  const p=d.profile||{};
  const box=(title,val,color)=>`<div class="card" style="border-left:4px solid ${color};border-radius:0">
    <div class="q">${title}</div><div class="a">${val||'<i style="color:#999">chưa có — admin cập nhật (train)</i>'}</div></div>`;
  const matters=d.matters.length? d.matters.map(m=>`<tr><td>${m.code||''}</td><td>${m.title}</td><td>${m.type||''}</td><td>${m.status}</td><td>${m.deadline||''}</td></tr>`).join('') : '<tr><td colspan=5>Chưa có vụ việc</td></tr>';
  const docs=d.documents.length? d.documents.map(x=>`<tr><td>${x.title}</td><td>${x.doc_type}</td><td>${x.summary||''}</td><td>${x.created_at}</td></tr>`).join('') : '<tr><td colspan=4>Chưa có tài liệu</td></tr>';
  document.getElementById('dossier').innerHTML=`
    <div class="card"><div class="q" style="font-size:18px">${d.client.name} ${d.client.department?'· '+d.client.department:''}</div></div>
    ${box('📋 Tóm tắt lịch sử dịch vụ',p.history,'#2e74b5')}
    ${box('⚠️ Vấn đề nổi bật',p.issues,'#f9a825')}
    ${box('🚨 Cảnh báo',p.warnings,'#c00000')}
    ${box('💡 Gợi ý / Đề xuất',p.suggestions,'#2e7d32')}
    <div class="card"><div class="q">📁 Vụ việc</div>
      <table><tr><th>Mã</th><th>Tên vụ việc</th><th>Loại</th><th>Trạng thái</th><th>Hạn</th></tr>${matters}</table></div>
    <div class="card"><div class="q">📎 Toàn bộ giấy tờ (tải về được)</div>
      <table><tr><th>Tên</th><th>Loại</th><th>Tóm tắt</th><th>Ngày</th></tr>${docs}</table></div>`;
}
async function loadUsers(){
  const r=await fetch('/users',{headers:H()});
  if(!r.ok){document.getElementById('userList').innerHTML='<p style="color:red">Chỉ admin xem được</p>';return;}
  const items=await r.json();
  document.getElementById('userList').innerHTML=`<table><tr><th>ID</th><th>Email</th><th>Tên</th><th>Cấp</th><th>Quyền duyệt</th><th></th></tr>`+
    items.map(u=>`<tr><td>${u.id}</td><td>${u.email}</td><td>${u.full_name||''}</td><td>${u.role}</td>
    <td>${u.can_review?'Có':'—'}</td>
    <td><button class="act ${u.can_review?'no':'ok'}" onclick="setRev(${u.id},${!u.can_review})">${u.can_review?'Thu quyền':'Cấp quyền'}</button></td></tr>`).join('')+`</table>`;
}
async function addUser(){
  const r=await fetch('/users',{method:'POST',headers:H(),body:JSON.stringify({
    email:document.getElementById('uemail').value,full_name:document.getElementById('uname').value,
    role:document.getElementById('urole').value,can_review:document.getElementById('ucanrev').checked,
    department_ids:(document.getElementById('udepts').value||'').split(',').map(s=>parseInt(s.trim())).filter(n=>!isNaN(n))})});
  if(r.ok){document.getElementById('uemail').value='';document.getElementById('uname').value='';loadUsers();}
  else alert('Lỗi: '+(await r.text()));
}
async function setRev(uid,grant){
  const r=await fetch(`/users/${uid}/review-permission?grant=${grant}`,{method:'POST',headers:H()});
  if(r.ok)loadUsers();else alert('Lỗi: '+(await r.text()));
}
</script></body></html>"""
