import React, { useEffect, useState } from 'react';
import * as api from '../../api';
import { useApp } from '../../context/AppContext';
import type { SuDungNguoiDung } from '../../types';
import { AlertTriangle, HardDrive, Loader2, RefreshCw } from 'lucide-react';

/**
 * "Ai đang dùng đến đâu" — bảng chỉ admin thấy (18/09/2026, chủ dự án: "chỉ
 * admin được toàn quyền xem user đã làm gì và đang tốn bộ nhớ bao nhiêu").
 *
 * Cố ý chỉ hiện SỐ ĐẾM và dung lượng: hội thoại, bản nháp, file đã tạo vẫn là
 * của riêng từng người — admin thấy khối lượng, không đọc nội dung ở đây.
 */
function dungLuong(bytes: number): string {
  if (!bytes) return '0';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export const SuDungCard: React.FC = () => {
  const { showToast } = useApp();
  const [data, setData] = useState<SuDungNguoiDung | null>(null);
  const [dangNap, setDangNap] = useState(false);
  const [mo, setMo] = useState(false);

  const nap = async () => {
    setDangNap(true);
    try {
      setData(await api.getSuDungNguoiDung());
    } catch (err: any) {
      showToast(err?.message || 'Không đọc được mức sử dụng.', 'error');
    } finally {
      setDangNap(false);
    }
  };

  useEffect(() => {
    if (mo && !data) void nap();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mo]);

  return (
    <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
      <button
        type="button"
        onClick={() => setMo((v) => !v)}
        className="w-full p-5 flex items-center justify-between gap-3 text-left"
      >
        <div>
          <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
            <HardDrive className="w-4 h-4 text-hds-gold" /> Ai đang dùng đến đâu
          </h3>
          <p className="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">
            Số hội thoại, bản nháp, file đã tạo và dung lượng đang giữ của từng người.
            Chỉ số đếm — nội dung vẫn là riêng của mỗi người.
          </p>
        </div>
        <span className="text-[11px] font-bold text-hds-navy dark:text-blue-300 shrink-0">
          {mo ? 'Thu gọn' : 'Xem'}
        </span>
      </button>

      {mo && (
        <div className="px-5 pb-5 space-y-3">
          <div className="flex items-center justify-between gap-3">
            <p className="text-[11px] text-slate-500 dark:text-slate-400">
              {data
                ? `Tổng dung lượng file tạm: ${dungLuong(data.tong_dung_luong)} · file tự xoá sau ${data.giu_ngay} ngày.`
                : 'Đang đọc…'}
            </p>
            <button
              type="button"
              onClick={() => void nap()}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-[11px] font-semibold"
            >
              <RefreshCw className={`w-3 h-3 ${dangNap ? 'animate-spin' : ''}`} /> Tải lại
            </button>
          </div>

          {!data ? (
            <p className="text-xs text-slate-500 flex items-center gap-1.5">
              <Loader2 className="w-4 h-4 animate-spin" /> Đang tính…
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="text-left text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-slate-700">
                    <th className="py-2 pr-3 font-semibold">Người dùng</th>
                    <th className="py-2 px-2 font-semibold text-right">Hội thoại</th>
                    <th className="py-2 px-2 font-semibold text-right">Tin nhắn</th>
                    <th className="py-2 px-2 font-semibold text-right">Bản nháp</th>
                    <th className="py-2 px-2 font-semibold text-right" title="Bộ hồ sơ đã điền mà người dùng bấm Lưu (tự xoá sau 7 ngày)">Hồ sơ đã lưu</th>
                    <th className="py-2 px-2 font-semibold text-right">Tài liệu đã nạp</th>
                    <th className="py-2 px-2 font-semibold text-right">File đang giữ</th>
                    <th className="py-2 px-2 font-semibold text-right">Dung lượng</th>
                    <th className="py-2 pl-2 font-semibold">Hoạt động cuối</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((u) => (
                    <tr
                      key={u.id}
                      className={`border-b border-slate-100 dark:border-slate-800 ${
                        u.active ? '' : 'opacity-50'
                      }`}
                    >
                      <td className="py-2 pr-3">
                        <span className="font-semibold text-slate-800 dark:text-slate-100">
                          {u.full_name}
                        </span>
                        <span className="block text-[10px] text-slate-400">{u.email}</span>
                      </td>
                      <td className="py-2 px-2 text-right">{u.hoi_thoai}</td>
                      <td className="py-2 px-2 text-right">{u.tin_nhan}</td>
                      <td className="py-2 px-2 text-right">{u.ban_nhap}</td>
                      <td className="py-2 px-2 text-right">{u.ho_so_da_luu ?? 0}</td>
                      <td className="py-2 px-2 text-right">{u.tai_lieu_da_nap}</td>
                      <td className="py-2 px-2 text-right">{u.file_dang_giu}</td>
                      <td className="py-2 px-2 text-right font-semibold">
                        {dungLuong(u.dung_luong)}
                      </td>
                      <td className="py-2 pl-2 text-slate-500 dark:text-slate-400">
                        {u.hoat_dong_cuoi || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.khong_ro_chu.so_file > 0 && (
                <p className="mt-2 text-[10px] text-slate-500 dark:text-slate-400 flex items-start gap-1">
                  <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" />
                  {data.khong_ro_chu.so_file} file tạm ({dungLuong(data.khong_ro_chu.bytes)}) sinh
                  trước khi hệ thống ghi chủ sở hữu nên chưa gắn được cho ai — số này tự về 0 sau
                  {' '}{data.giu_ngay} ngày.
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
