import React, { useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { bundleDangChay, bundleTrenMayChu, coBanMoi } from '../banMoi';

/** Kiểm ngay sau khi trang dựng xong (index.html có thể đã là bản cache). */
const KIEM_LAN_DAU_MS = 3_000;
/** Rồi định kỳ; thêm mỗi lần người dùng quay lại tab — lúc bản cũ hay lộ nhất. */
const CHU_KY_MS = 5 * 60_000;

/**
 * Dải báo "có bản mới — tải lại" ở đầu trang. Không tự tải lại: người dùng có
 * thể đang gõ dở hay đang chờ câu trả lời, chỉ họ mới biết lúc nào tiện.
 */
export const BanMoiBanner: React.FC = () => {
  const [coMoi, setCoMoi] = useState(false);

  useEffect(() => {
    const dangChay = bundleDangChay();
    if (!dangChay) return undefined; // dev server: không có bundle băm để so

    let daNgung = false;
    let dangKiem = false;
    const kiem = async () => {
      if (dangKiem || daNgung) return;
      dangKiem = true;
      try {
        const moi = await bundleTrenMayChu();
        if (!daNgung && coBanMoi(dangChay, moi)) setCoMoi(true);
      } catch {
        // mất mạng tạm thời — lần sau kiểm lại, không làm phiền
      } finally {
        dangKiem = false;
      }
    };
    const khiHienLai = () => {
      if (document.visibilityState === 'visible') void kiem();
    };

    const lanDau = window.setTimeout(kiem, KIEM_LAN_DAU_MS);
    const dinhKy = window.setInterval(kiem, CHU_KY_MS);
    document.addEventListener('visibilitychange', khiHienLai);
    window.addEventListener('focus', khiHienLai);
    return () => {
      daNgung = true;
      window.clearTimeout(lanDau);
      window.clearInterval(dinhKy);
      document.removeEventListener('visibilitychange', khiHienLai);
      window.removeEventListener('focus', khiHienLai);
    };
  }, []);

  if (!coMoi) return null;
  return (
    <div
      role="status"
      className="bg-hds-gold text-hds-navy text-xs sm:text-sm font-semibold px-3 py-2 flex flex-wrap items-center justify-center gap-x-3 gap-y-1.5 shadow-md"
    >
      <span>HDS AI vừa có bản cập nhật — trang này đang chạy bản cũ.</span>
      <button
        type="button"
        onClick={() => window.location.reload()}
        className="inline-flex items-center gap-1.5 bg-hds-navy text-hds-gold px-3 py-1 rounded-lg hover:bg-hds-navy-light transition-colors"
      >
        <RefreshCw className="w-3.5 h-3.5" />
        Tải lại ngay
      </button>
    </div>
  );
};
