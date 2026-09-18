import React, { useEffect, useState } from 'react';
import * as api from '../../api';
import { useApp } from '../../context/AppContext';
import type { HoSoDaLuu } from '../../types';
import {
  AlertTriangle,
  Check,
  Download,
  Eye,
  FileText,
  Loader2,
  Package,
  Pencil,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';

/**
 * Mở lại một BỘ HỒ SƠ ĐÃ ĐIỀN mà người dùng đã bấm Lưu (18/09/2026).
 *
 * Bản ghi chỉ trỏ tới file nằm trong hàng tạm 7 ngày, nên mỗi file mang cờ
 * `con`: dọn rồi thì nút tải phải tắt kèm lý do, đừng để người dùng bấm xong
 * mới nhận lỗi 404. Hồ sơ là của riêng người tạo — máy chủ đã chặn, giao diện
 * chỉ hiển thị đúng phần mình có.
 */
interface Props {
  ma: string;
  /** Bộ mẫu gốc còn trong danh sách → cho phép mở luồng điền lại. */
  coBoMau?: boolean;
  onClose: () => void;
  /** Đã xoá bản ghi — cột trái nạp lại. */
  onXoa?: () => void;
  onDoiTen?: () => void;
  /** Bấm "Điền lại bộ này" — cha mở panel Điền bộ với bo_id. */
  onDienLai?: (boId: number) => void;
}

const ngay = (luc: number) =>
  new Date((luc || 0) * 1000).toLocaleString('vi-VN', {
    hour: '2-digit',
    minute: '2-digit',
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });

export const HoSoDaLuuModal: React.FC<Props> = ({
  ma,
  coBoMau,
  onClose,
  onXoa,
  onDoiTen,
  onDienLai,
}) => {
  const { showToast } = useApp();
  const [ho, setHo] = useState<HoSoDaLuu | null>(null);
  const [dangNap, setDangNap] = useState(true);
  const [loi, setLoi] = useState('');
  const [suaTen, setSuaTen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [xem, setXem] = useState<{ ten: string; doan: string[]; cat_bot: boolean } | null>(null);
  const [xemBusy, setXemBusy] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setDangNap(true);
    api
      .getHoSoDaLuu(ma)
      .then((res) => {
        if (alive) setHo(res);
      })
      .catch((err: any) => {
        if (alive) setLoi(err?.message || 'Không mở được hồ sơ đã lưu.');
      })
      .finally(() => {
        if (alive) setDangNap(false);
      });
    return () => {
      alive = false;
    };
  }, [ma]);

  const xemNhanh = async (token: string, ten: string) => {
    setXemBusy(token);
    try {
      const res = await api.xemTemplateFill(token);
      setXem({ ten: res.ten_file || ten, doan: res.doan || [], cat_bot: !!res.cat_bot });
    } catch (err: any) {
      showToast(err?.message || 'Không xem nhanh được file này.', 'error');
    } finally {
      setXemBusy(null);
    }
  };

  const tai = async (token: string, ten: string, soTrong: number) => {
    if (
      soTrong > 0 &&
      !window.confirm(
        `«${ten}» còn ${soTrong} chỗ trống chưa có dữ liệu — file tải về sẽ hiện nguyên ` +
          'các ô {{…}} ở những chỗ đó.\n\nVẫn tải về?'
      )
    ) {
      return;
    }
    try {
      await api.downloadTemplateFill(token, ten);
    } catch (err: any) {
      showToast(err?.message || 'Không tải được file.', 'error');
    }
  };

  const luuTen = async () => {
    if (!ho || suaTen === null) return;
    setBusy(true);
    try {
      const res = await api.renameHoSoDaLuu(ho.ma, suaTen.trim() || ho.ten);
      setHo({ ...ho, ten: res.ten || ho.ten });
      setSuaTen(null);
      onDoiTen?.();
    } catch (err: any) {
      showToast(err?.message || 'Không đổi được tên.', 'error');
    } finally {
      setBusy(false);
    }
  };

  const xoa = async () => {
    if (!ho) return;
    if (
      !window.confirm(
        `Xoá «${ho.ten}» khỏi danh sách đã lưu?\n\nFile đã tải về máy bạn vẫn còn.`
      )
    ) {
      return;
    }
    setBusy(true);
    try {
      await api.deleteHoSoDaLuu(ho.ma);
      showToast('Đã xoá khỏi danh sách.', 'success');
      onXoa?.();
      onClose();
    } catch (err: any) {
      showToast(err?.message || 'Không xoá được.', 'error');
    } finally {
      setBusy(false);
    }
  };

  const hetHan = ho ? ho.so_file_con === 0 : false;

  return (
    <div
      className="fixed inset-0 z-50 bg-slate-950/60 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-3xl max-h-[90vh] flex flex-col bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-2xl"
      >
        <div className="p-5 border-b border-slate-200 dark:border-slate-800 flex items-start justify-between gap-3">
          <div className="min-w-0">
            {suaTen === null ? (
              <h3 className="font-bold text-base flex items-center gap-2 min-w-0">
                <span className="truncate">{ho?.ten || 'Bộ hồ sơ đã lưu'}</span>
                {ho && (
                  <button
                    type="button"
                    onClick={() => setSuaTen(ho.ten)}
                    className="shrink-0 p-1 rounded-lg text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
                    title="Đổi tên"
                    aria-label="Đổi tên hồ sơ đã lưu"
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                )}
              </h3>
            ) : (
              <div className="flex items-center gap-2">
                <input
                  autoFocus
                  value={suaTen}
                  onChange={(e) => setSuaTen(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') void luuTen();
                    if (e.key === 'Escape') setSuaTen(null);
                  }}
                  className="px-2.5 py-1.5 rounded-xl border border-slate-300 dark:border-slate-700 dark:bg-slate-900 text-xs outline-none focus:ring-2 focus:ring-hds-blue"
                />
                <button
                  type="button"
                  onClick={() => void luuTen()}
                  disabled={busy}
                  className="p-1.5 rounded-lg bg-hds-navy text-hds-gold disabled:opacity-50"
                  aria-label="Lưu tên"
                >
                  <Check className="w-3.5 h-3.5" />
                </button>
              </div>
            )}
            {ho && (
              <p className="text-[11px] text-slate-500 mt-0.5">
                {ho.kieu === 'ban_cu' ? 'Dựng theo bộ hồ sơ khách cũ' : ho.bo_ten || 'Bộ mẫu hồ sơ'}
                {' · '}lưu lúc {ngay(ho.luc)}
                {' · '}
                <span className={ho.con_lai_ngay < 1 ? 'text-hds-red font-bold' : ''}>
                  còn{' '}
                  {ho.con_lai_ngay < 1
                    ? `${Math.max(1, Math.round(ho.con_lai_ngay * 24))} giờ`
                    : `${Math.floor(ho.con_lai_ngay)} ngày`}
                </span>
              </p>
            )}
          </div>
          <button type="button" onClick={onClose} aria-label="Đóng">
            <X className="w-5 h-5 text-slate-400" />
          </button>
        </div>

        <div className="p-5 overflow-y-auto space-y-3">
          {dangNap && (
            <p className="py-10 flex items-center justify-center gap-2 text-xs text-slate-500">
              <Loader2 className="w-4 h-4 animate-spin" /> Đang mở…
            </p>
          )}
          {loi && (
            <p className="p-3 rounded-xl bg-red-50 dark:bg-red-950/40 text-[11px] text-red-800 dark:text-red-200">
              {loi}
            </p>
          )}

          {ho && (
            <>
              {hetHan && (
                <p className="p-3 rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50/60 dark:bg-amber-950/30 text-[11px] text-amber-900 dark:text-amber-200 flex items-start gap-2">
                  <AlertTriangle className="w-4 h-4 shrink-0" />
                  File kết quả đã quá hạn 7 ngày và bị dọn khỏi máy chủ. Bảng dữ liệu bên dưới
                  vẫn còn — điền lại bộ là ra đúng bộ file cũ.
                </p>
              )}

              <div className="p-3 rounded-xl border border-slate-200 dark:border-slate-700 text-[11px] text-slate-600 dark:text-slate-300">
                {ho.so_file_con}/{ho.so_file} file còn tải được
                {ho.so_o > 0 && (
                  <>
                    {' · '}
                    {ho.so_da_dien}/{ho.so_o} ô có dữ liệu
                  </>
                )}
                {ho.so_thieu > 0 && (
                  <span className="text-amber-700 dark:text-amber-300 font-semibold">
                    {' · '}còn {ho.so_thieu} ô trống
                  </span>
                )}
              </div>

              {ho.zip_token && ho.zip_con && (
                <button
                  type="button"
                  onClick={() => void tai(ho.zip_token as string, `${ho.ten}.zip`, 0)}
                  className="w-full px-3 py-2 rounded-xl border border-hds-navy text-hds-navy dark:text-blue-300 dark:border-blue-700 text-[11px] font-bold flex items-center justify-center gap-1.5 hover:bg-hds-soft dark:hover:bg-slate-800"
                >
                  <Package className="w-3.5 h-3.5" /> Tải cả bộ (.zip)
                </button>
              )}

              <ul className="space-y-1.5">
                {ho.files.map((f) => (
                  <li
                    key={f.token}
                    className="p-2.5 rounded-xl border border-slate-200 dark:border-slate-700 flex items-center gap-2"
                  >
                    <FileText className="w-4 h-4 text-slate-400 shrink-0" />
                    <span className="flex-1 min-w-0">
                      <span className="block text-[11px] font-semibold truncate">{f.ten_file}</span>
                      {f.so_trong > 0 && (
                        <span className="block text-[10px] text-amber-700 dark:text-amber-300">
                          còn {f.so_trong} chỗ trống
                        </span>
                      )}
                    </span>
                    {f.con === false ? (
                      <span className="text-[10px] text-slate-400">đã quá hạn</span>
                    ) : (
                      <>
                        <button
                          type="button"
                          onClick={() => void xemNhanh(f.token, f.ten_file)}
                          className="px-2 py-1 rounded-lg border border-slate-300 dark:border-slate-700 text-[10px] font-bold flex items-center gap-1 hover:bg-slate-50 dark:hover:bg-slate-800"
                        >
                          {xemBusy === f.token ? (
                            <Loader2 className="w-3 h-3 animate-spin" />
                          ) : (
                            <Eye className="w-3 h-3" />
                          )}
                          Xem nhanh
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            api
                              .previewTemplateFill(f.token)
                              .catch((e: any) =>
                                showToast(e?.message || 'Không mở được bản PDF.', 'error')
                              )
                          }
                          className="px-2 py-1 rounded-lg border border-slate-300 dark:border-slate-700 text-[10px] font-bold hover:bg-slate-50 dark:hover:bg-slate-800"
                        >
                          PDF
                        </button>
                        <button
                          type="button"
                          onClick={() => void tai(f.token, f.ten_ket_qua || f.ten_file, f.so_trong)}
                          className="px-2 py-1 rounded-lg bg-hds-navy text-hds-gold text-[10px] font-bold flex items-center gap-1"
                        >
                          <Download className="w-3 h-3" /> Tải
                        </button>
                      </>
                    )}
                  </li>
                ))}
              </ul>

              {(ho.da_dien || []).length > 0 && (
                <details className="p-3 rounded-xl border border-slate-200 dark:border-slate-700">
                  <summary className="text-xs font-bold text-slate-700 dark:text-slate-300 cursor-pointer">
                    Dữ liệu đã dùng ({(ho.da_dien || []).length} ô)
                  </summary>
                  <div className="mt-2 max-h-64 overflow-y-auto grid sm:grid-cols-2 gap-1.5">
                    {(ho.da_dien || []).map((o) => (
                      <p
                        key={o.khoa}
                        className="text-[10px] text-slate-600 dark:text-slate-300 truncate"
                        title={`${o.literal} = ${o.gia_tri}`}
                      >
                        <b>{o.literal || o.khoa}</b>: {o.gia_tri}
                      </p>
                    ))}
                  </div>
                </details>
              )}

              {(ho.con_thieu || []).length > 0 && (
                <details className="p-3 rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-950/20">
                  <summary className="text-xs font-bold text-amber-900 dark:text-amber-200 cursor-pointer">
                    {(ho.con_thieu || []).length} ô chưa có dữ liệu lúc lưu
                  </summary>
                  <p className="mt-1 text-[10px] text-amber-800 dark:text-amber-300">
                    {(ho.con_thieu || []).map((o) => o.goi_y || o.literal || o.khoa).join(' · ')}
                  </p>
                </details>
              )}
            </>
          )}
        </div>

        <div className="p-4 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between gap-2">
          <button
            type="button"
            onClick={() => void xoa()}
            disabled={busy || !ho}
            className="px-3 py-2 rounded-xl text-[11px] font-bold text-red-600 hover:bg-red-50 dark:hover:bg-red-950/40 flex items-center gap-1.5 disabled:opacity-40"
          >
            <Trash2 className="w-3.5 h-3.5" /> Xoá khỏi danh sách
          </button>
          <div className="flex items-center gap-2">
            {ho?.bo_id && coBoMau && onDienLai && (
              <button
                type="button"
                onClick={() => onDienLai(ho.bo_id as number)}
                className="px-3 py-2 rounded-xl bg-hds-navy text-hds-gold text-[11px] font-bold flex items-center gap-1.5"
              >
                <Sparkles className="w-3.5 h-3.5" /> Điền lại bộ này
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
            >
              Đóng
            </button>
          </div>
        </div>
      </div>

      {xem && (
        <div
          className="fixed inset-0 z-[60] bg-slate-950/60 backdrop-blur-sm flex items-center justify-center p-4"
          onClick={(e) => {
            e.stopPropagation();
            setXem(null);
          }}
          role="presentation"
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-3xl max-h-[85vh] flex flex-col bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-2xl"
          >
            <div className="p-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between gap-3">
              <h4 className="text-sm font-bold truncate">Xem nhanh · {xem.ten}</h4>
              <button type="button" onClick={() => setXem(null)} aria-label="Đóng">
                <X className="w-5 h-5 text-slate-400" />
              </button>
            </div>
            <div className="p-5 overflow-y-auto space-y-1.5 font-serif text-[13px] leading-relaxed">
              {xem.doan.map((d, i) => (
                <p
                  key={i}
                  className={
                    d.includes('{{')
                      ? 'text-amber-700 dark:text-amber-300'
                      : 'text-slate-800 dark:text-slate-200'
                  }
                >
                  {d}
                </p>
              ))}
              {xem.cat_bot && (
                <p className="pt-2 text-[11px] italic text-slate-500">
                  … (bản xem nhanh chỉ hiển thị phần đầu — tải file về để xem trọn vẹn)
                </p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
