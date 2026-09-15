/*
 * hds-chat.js — nhúng khung "Hỏi luật sư HDS" vào website bất kỳ.
 *
 * Dán MỘT dòng vào cuối <body> của website HDS:
 *   <script src="https://app.hdslaw.vn/embed/hds-chat.js" defer></script>
 *
 * Tuỳ chọn qua data-*:
 *   data-api="https://app.hdslaw.vn"   máy chủ AI (mặc định = nơi tải script)
 *   data-label="Hỏi luật sư"           chữ trên nút nổi
 *   data-position="left"               nút ở góc trái (mặc định phải)
 *   data-open="1"                      mở sẵn khung khi tải trang
 *
 * Nút nổi góc màn hình → bấm mở iframe chat.html (cùng thư mục). Mọi thứ
 * nằm trong iframe nên CSS của website chủ không ảnh hưởng và ngược lại.
 */
(function () {
  if (window.__hdsChatLoaded) return;
  window.__hdsChatLoaded = true;
  var me = document.currentScript || (function () {
    var s = document.getElementsByTagName('script');
    return s[s.length - 1];
  })();
  var src = (me && me.src) || '';
  var base = src.replace(/\/embed\/[^/]*$/, '');
  var api = (me && me.getAttribute('data-api')) || base || location.origin;
  var label = (me && me.getAttribute('data-label')) || 'Hỏi luật sư HDS';
  var left = me && me.getAttribute('data-position') === 'left';
  var url = (base || api) + '/embed/chat.html?api=' + encodeURIComponent(api);

  var css = document.createElement('style');
  css.textContent =
    '#hds-chat-btn{position:fixed;bottom:20px;' + (left ? 'left' : 'right') + ':20px;z-index:2147483000;' +
    'background:#1f3864;color:#f9a825;border:0;border-radius:999px;padding:12px 18px;font:700 14px system-ui,sans-serif;' +
    'box-shadow:0 8px 24px rgba(0,0,0,.25);cursor:pointer;display:flex;align-items:center;gap:8px}' +
    '#hds-chat-btn:hover{background:#27447a}' +
    '#hds-chat-box{position:fixed;bottom:76px;' + (left ? 'left' : 'right') + ':20px;z-index:2147483000;width:380px;max-width:calc(100vw - 32px);' +
    'height:560px;max-height:calc(100vh - 100px);border:0;border-radius:16px;box-shadow:0 16px 48px rgba(0,0,0,.3);display:none;background:#fff}' +
    '#hds-chat-box.open{display:block}';
  document.head.appendChild(css);

  var btn = document.createElement('button');
  btn.id = 'hds-chat-btn';
  btn.type = 'button';
  btn.setAttribute('aria-label', label);
  btn.innerHTML = '<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#22c55e"></span>' + label;
  var box = document.createElement('iframe');
  box.id = 'hds-chat-box';
  box.title = label;
  box.setAttribute('loading', 'lazy');
  var loaded = false;
  function toggle(force) {
    var open = typeof force === 'boolean' ? force : !box.classList.contains('open');
    if (open && !loaded) { box.src = url; loaded = true; }
    box.classList.toggle('open', open);
    btn.textContent = '';
    btn.innerHTML = open
      ? '&#10005; Đóng'
      : '<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#22c55e"></span>' + label;
  }
  btn.addEventListener('click', function () { toggle(); });
  document.body.appendChild(box);
  document.body.appendChild(btn);
  if (me && me.getAttribute('data-open') === '1') toggle(true);
  window.HDSChat = { open: function () { toggle(true); }, close: function () { toggle(false); } };
})();
