/**
 * Phát hiện máy chủ đã có bản build giao diện mới hơn bản tab này đang chạy.
 *
 * Vì sao cần (06/09/2026): deploy xong, tab đang mở vẫn chạy JS cũ. index.html
 * không có header chống cache nên trình duyệt giữ bản cũ hàng giờ (Cloudflare
 * còn gắn max-age 4 giờ cho file JS), tab treo sẵn từ hôm trước thì không tải
 * gì cả. Người dùng thấy "đã update mà lỗi cũ còn nguyên" và không có cách nào
 * tự phân biệt tại trình duyệt hay tại mã.
 *
 * Cách nhận biết: Vite đặt mã băm nội dung vào tên bundle (index-XXXX.js).
 * So tên bundle trang này đang chạy với tên trong index.html mới nhất trên
 * máy chủ — khác nhau tức là đã có bản mới.
 */
export const BUILD_ID: string = import.meta.env.VITE_BUILD_ID || 'dev';

const RE_BUNDLE = /\/assets\/index-[A-Za-z0-9_-]+\.js/;

/** Rút tên bundle chính từ một chuỗi (src của thẻ script, hoặc cả index.html). */
export function rutTenBundle(text: string): string | null {
  const m = text.match(RE_BUNDLE);
  return m ? m[0] : null;
}

/** Bundle mà trang HIỆN TẠI đang chạy; null khi chạy dev server (không băm tên). */
export function bundleDangChay(doc: Document = document): string | null {
  const el = doc.querySelector<HTMLScriptElement>(
    'script[type="module"][src*="/assets/index-"]'
  );
  return rutTenBundle(el?.getAttribute('src') ?? '');
}

/** Tải index.html mới nhất, bỏ qua mọi lớp cache, rút tên bundle trong đó. */
export async function bundleTrenMayChu(signal?: AbortSignal): Promise<string | null> {
  const res = await fetch(`/index.html?_=${Date.now()}`, {
    cache: 'no-store',
    credentials: 'same-origin',
    signal,
  });
  if (!res.ok) return null;
  return rutTenBundle(await res.text());
}

/**
 * Có bản mới khi biết CẢ HAI tên và chúng khác nhau. Thiếu một bên (dev server,
 * máy chủ trả lỗi, index.html đổi khuôn) thì không kết luận — thà im còn hơn
 * bắt người dùng tải lại vô ích.
 */
export function coBanMoi(dangChay: string | null, trenMayChu: string | null): boolean {
  return Boolean(dangChay && trenMayChu && dangChay !== trenMayChu);
}
