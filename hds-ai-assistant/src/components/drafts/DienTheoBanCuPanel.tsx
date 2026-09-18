import React, { useRef, useState } from 'react';
import * as api from '../../api';
import { useApp } from '../../context/AppContext';
import type { HoSoCuResult } from '../../types';
import {
  AlertTriangle,
  ArrowRight,
  Download,
  Eye,
  FileText,
  FolderClock,
  Loader2,
  Package,
  Save,
  Sparkles,
  Upload,
  UserPlus,
  X,
} from 'lucide-react';

/**
 * Dựng bộ hồ sơ cho khách MỚI theo bộ hồ sơ khách CŨ — KHÔNG cần mã chỗ trống
 * (18/09/2026, chủ dự án: "tôi tải lên bộ hồ sơ khách cũ và form thu thập
 * thông tin khách mới, AI đọc hiểu rồi tự thay").
 *
 * Bộ cũ giữ nguyên định dạng Word; máy chỉ thay những chuỗi mang thông tin chủ
 * thể. Giá trị mới BẮT BUỘC có trong hồ sơ khách mới người dùng vừa tải lên —
 * chữ nào không có ở đó thì không được phép chui vào file.
 */
const DINH_DANG_MOI = '.docx,.pdf,.doc,.txt,.md,.jpg,.jpeg,.png,.webp,.tif,.tiff,.bmp';

interface Props {
  /** Vừa lưu xong — cột "Bộ hồ sơ đã điền" bên trái nạp lại. */
  onSaved?: () => void;
}

export const DienTheoBanCuPanel: React.FC<Props> = ({ onSaved }) => {
  const { showToast } = useApp();
  const [fileCu, setFileCu] = useState<File[]>([]);
  const [fileMoi, setFileMoi] = useState<File[]>([]);
  const [ghiChu, setGhiChu] = useState('');
  const [busy, setBusy] = useState(false);
  const [tienTrinh, setTienTrinh] = useState(0);
  const [ketQua, setKetQua] = useState<HoSoCuResult | null>(null);
  const [moBang, setMoBang] = useState<string | null>(null);
  const [xem, setXem] = useState<{ ten: string; doan: string[]; cat_bot: boolean } | null>(null);
  const [xemBusy, setXemBusy] = useState<string | null>(null);
  const [tenLuu, setTenLuu] = useState('');
  const [luuBusy, setLuuBusy] = useState(false);
  const [daLuu, setDaLuu] = useState(false);
  const cuRef = useRef<HTMLInputElement | null>(null);
  const moiRef = useRef<HTMLInputElement | null>(null);

  /** Nhận MẢNG File, không nhận FileList — xem chú thích cùng lỗi ở
   *  DienBoMauPanel: reset ô input làm rỗng FileList trước khi React đọc. */
  const them = (ds: File[], dat: React.Dispatch<React.SetStateAction<File[]>>) => {
    if (!ds.length) return;
    dat((truoc) => {
      const gop = [...truoc];
      ds.forEach((f) => {
        if (!gop.some((x) => x.name === f.name && x.size === f.size)) gop.push(f);
      });
      return gop.slice(0, 10);
    });
  };

  const chay = async () => {
    if (busy) return;
    if (!fileCu.length) {
      showToast('Tải lên bộ hồ sơ khách cũ (.docx) trước đã.', 'error');
      return;
    }
    if (!fileMoi.length && !ghiChu.trim()) {
      showToast('Cần thông tin khách mới: tải form lên hoặc gõ vào ô ghi chú.', 'error');
      return;
    }
    setBusy(true);
    setTienTrinh(0);
    try {
      const res = await api.dienTheoBanCu({
        cu: fileCu,
        moi: fileMoi,
        ghiChu,
        onProgress: setTienTrinh,
      });
      setKetQua(res);
      setDaLuu(false);
      setTenLuu((truoc) =>
        truoc || `Hồ sơ khách mới — ${new Date().toLocaleDateString('vi-VN')}`);
      const xong = (res.files || []).filter((f) => f.token).length;
      showToast(`Đã dựng ${xong}/${(res.files || []).length} file cho khách mới.`,
                xong ? 'success' : 'error');
    } catch (err: any) {
      showToast(err?.message || 'Không dựng được bộ hồ sơ.', 'error');
    } finally {
      setBusy(false);
      setTienTrinh(0);
    }
  };

  const xemNhanh = async (token: string | null, ten: string) => {
    if (!token) return;
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

  const tai = async (token: string | null, ten: string, soThay: number) => {
    if (!token) return;
    if (
      soThay === 0 &&
      !window.confirm(
        `«${ten}» chưa thay được chỗ nào — nội dung vẫn là của khách CŨ.\n\nVẫn tải về?`
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

  /** Giữ bộ vừa dựng lại để mở trong 7 ngày (chỉ ghi con trỏ tới token). */
  const luuLai = async () => {
    if (!ketQua || luuBusy) return;
    const files = (ketQua.files || [])
      .filter((f) => f.token)
      .map((f) => ({
        token: f.token as string,
        ten_file: f.ten_file,
        ten_ket_qua: f.ten_ket_qua || f.ten_file,
        so_trong: f.so_thay ? 0 : 1,
      }));
    if (!files.length) {
      showToast('Chưa có file nào dựng xong để lưu.', 'error');
      return;
    }
    const chuaThay = (ketQua.chua_thay_duoc || []).length;
    if (
      chuaThay > 0 &&
      !window.confirm(
        `${chuaThay} file chưa thay được chỗ nào — nội dung vẫn là của khách CŨ.` +
          '\n\nVẫn lưu bản này?'
      )
    ) {
      return;
    }
    setLuuBusy(true);
    try {
      await api.luuHoSoDaDien({
        ten: tenLuu.trim() || 'Hồ sơ theo bản khách cũ',
        kieu: 'ban_cu',
        files,
        zip_token: ketQua.zip_token,
        so_o: 0,
        da_dien: (ketQua.truong_doc_duoc || []).map((t) => ({
          khoa: t.khoa, literal: t.nhan, gia_tri: t.gia_tri,
          nguon: 'hồ sơ khách mới',
        })),
      });
      setDaLuu(true);
      showToast('Đã lưu — mở lại ở cột «Bộ hồ sơ đã điền» bên trái (giữ 7 ngày).',
                'success');
      onSaved?.();
    } catch (err: any) {
      showToast(err?.message || 'Không lưu được bộ hồ sơ.', 'error');
    } finally {
      setLuuBusy(false);
    }
  };

  const oTaiLen = (
    nhan: string,
    mo_ta: string,
    ds: File[],
    dat: React.Dispatch<React.SetStateAction<File[]>>,
    inputRef: React.MutableRefObject<HTMLInputElement | null>,
    accept: string,
    icon: React.ReactNode
  ) => (
    <div className="p-3 rounded-xl border border-slate-200 dark:border-slate-700">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold text-slate-700 dark:text-slate-300 flex items-center gap-1.5">
            {icon} {nhan}
          </p>
          <p className="mt-0.5 text-[10px] leading-relaxed text-slate-500 dark:text-slate-400">
            {mo_ta}
          </p>
        </div>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={accept}
          className="sr-only"
          onChange={(e) => {
            const chon = Array.from(e.target.files || []);   // chụp TRƯỚC khi reset
            e.target.value = '';
            them(chon, dat);
          }}
        />
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={busy}
          className="shrink-0 px-3 py-2 rounded-xl border border-hds-navy text-hds-navy dark:text-blue-300 dark:border-blue-700 text-[11px] font-bold flex items-center gap-1.5 hover:bg-hds-soft dark:hover:bg-slate-800 disabled:opacity-40"
        >
          <Upload className="w-3.5 h-3.5" /> Chọn file
        </button>
      </div>
      {ds.length > 0 && (
        <ul className="mt-2 space-y-1">
          {ds.map((f) => (
            <li
              key={`${f.name}-${f.size}`}
              className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-slate-50 dark:bg-slate-800 text-[11px]"
            >
              <FileText className="w-3.5 h-3.5 text-slate-400 shrink-0" />
              <span className="flex-1 truncate">{f.name}</span>
              <button
                type="button"
                aria-label={`Bỏ ${f.name}`}
                onClick={() => dat((truoc) => truoc.filter((x) => x !== f))}
                className="text-slate-400 hover:text-hds-red"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="p-3 rounded-xl border border-hds-navy/30 dark:border-blue-900 bg-hds-soft dark:bg-slate-800/60">
        <p className="text-xs font-bold text-hds-navy dark:text-blue-200 flex items-center gap-1.5">
          <FolderClock className="w-4 h-4 text-hds-gold" /> Làm theo bộ hồ sơ khách cũ — không cần
          mã chỗ trống
        </p>
        <p className="mt-1 text-[11px] leading-relaxed text-slate-600 dark:text-slate-300">
          Dùng khi công ty <b>chưa có bộ mẫu đặt sẵn</b>: tải lên trọn bộ hồ sơ của một khách đã
          làm xong + thông tin khách mới. Máy đọc hiểu từng văn bản, giữ nguyên định dạng Word và
          chỉ thay những chỗ mang <b>thông tin chủ thể</b> (tên, mã số thuế, địa chỉ, người đại
          diện, số giấy tờ…). Điều khoản, nghĩa vụ, con số pháp lý giữ nguyên.
        </p>
      </div>

      {oTaiLen(
        'Bước 1 · Bộ hồ sơ khách CŨ (.docx)',
        'Tối đa 10 file Word. Đây là khuôn: định dạng, thể thức, điều khoản của bộ mới sẽ y như bộ này.',
        fileCu,
        setFileCu,
        cuRef,
        '.docx',
        <FolderClock className="w-4 h-4 text-hds-gold" />
      )}

      {oTaiLen(
        'Bước 2 · Thông tin khách MỚI',
        'Form thu thập thông tin, CCCD, giấy phép… (PDF, ảnh, Word đều được). Máy chỉ điền những gì đọc thấy ở đây.',
        fileMoi,
        setFileMoi,
        moiRef,
        DINH_DANG_MOI,
        <UserPlus className="w-4 h-4 text-hds-gold" />
      )}

      <label className="block space-y-1">
        <span className="text-xs font-bold text-slate-700 dark:text-slate-300">
          Ghi chú thêm về khách mới (gõ tay)
        </span>
        <textarea
          rows={3}
          value={ghiChu}
          onChange={(e) => setGhiChu(e.target.value)}
          placeholder="Ví dụ: Tên công ty mới là CÔNG TY CỔ PHẦN XYZ, MST 0209988776, người đại diện bà Lê Thị B — Chủ tịch HĐQT, ký ngày 20/09/2026."
          className="w-full px-3 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 dark:bg-slate-800 text-xs resize-y outline-none focus:ring-2 focus:ring-hds-blue"
        />
        <span className="block text-[10px] text-slate-500 dark:text-slate-400">
          Máy chỉ được phép điền những giá trị <b>có mặt</b> trong hai bước trên — chữ nào không
          thấy ở đâu thì bỏ qua và báo lại, không tự bịa.
        </span>
      </label>

      <button
        type="button"
        onClick={chay}
        disabled={busy || !fileCu.length}
        className="w-full px-4 py-2.5 rounded-xl bg-hds-navy text-hds-gold text-xs font-bold flex items-center justify-center gap-2 disabled:opacity-50"
      >
        {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
        {busy
          ? tienTrinh > 0 && tienTrinh < 100
            ? `Đang tải lên ${tienTrinh}%…`
            : 'Đang đọc và thay thông tin từng file…'
          : `Dựng bộ hồ sơ cho khách mới (${fileCu.length} file)`}
      </button>

      {ketQua && (
        <div className="space-y-3">
          <div className="p-3 rounded-xl border border-emerald-200 dark:border-emerald-900 bg-emerald-50/60 dark:bg-emerald-950/30">
            <p className="text-xs font-bold text-emerald-900 dark:text-emerald-200">
              Đã dựng {(ketQua.files || []).filter((f) => f.token).length}/
              {(ketQua.files || []).length} file từ bộ hồ sơ cũ
            </p>
            {(ketQua.truong_doc_duoc || []).length > 0 && (
              <p className="mt-1 text-[10px] text-emerald-900/80 dark:text-emerald-200/80">
                Đọc được từ hồ sơ mới:{' '}
                {ketQua.truong_doc_duoc.map((t) => `${t.nhan}: ${t.gia_tri}`).join(' · ')}
              </p>
            )}
            {(ketQua.loi_tai_len || []).map((l) => (
              <p key={l.ten_file} className="mt-1 text-[10px] text-hds-red">
                «{l.ten_file}»: {l.loi}
              </p>
            ))}
          </div>

          {(ketQua.canh_bao || []).length > 0 && (
            <div className="p-3 rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50/60 dark:bg-amber-950/30">
              <p className="text-xs font-bold text-amber-900 dark:text-amber-200 flex items-center gap-1.5">
                <AlertTriangle className="w-4 h-4" /> Phải kiểm tra trước khi gửi
              </p>
              <ul className="mt-1 space-y-0.5">
                {ketQua.canh_bao.map((c, i) => (
                  <li key={i} className="text-[10px] text-amber-900 dark:text-amber-200/90">
                    · {c}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {ketQua.zip_token && (
            <button
              type="button"
              onClick={() => tai(ketQua.zip_token, 'bo ho so khach moi.zip', 1)}
              className="w-full px-3 py-2 rounded-xl border border-hds-navy text-hds-navy dark:text-blue-300 dark:border-blue-700 text-[11px] font-bold flex items-center justify-center gap-1.5 hover:bg-hds-soft dark:hover:bg-slate-800"
            >
              <Package className="w-3.5 h-3.5" /> Tải cả bộ (.zip)
            </button>
          )}

          <ul className="space-y-1.5">
            {(ketQua.files || []).map((f) => (
              <li key={f.ten_file} className="p-2.5 rounded-xl border border-slate-200 dark:border-slate-700">
                <div className="flex items-center gap-2">
                  <FileText className="w-4 h-4 text-slate-400 shrink-0" />
                  <span className="flex-1 text-[11px] font-semibold truncate">{f.ten_file}</span>
                  {f.token ? (
                    <>
                      <button
                        type="button"
                        onClick={() => xemNhanh(f.token, f.ten_file)}
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
                          api.previewTemplateFill(f.token as string).catch((e: any) =>
                            showToast(e?.message || 'Không mở được bản PDF.', 'error')
                          )
                        }
                        className="px-2 py-1 rounded-lg border border-slate-300 dark:border-slate-700 text-[10px] font-bold hover:bg-slate-50 dark:hover:bg-slate-800"
                      >
                        PDF
                      </button>
                      <button
                        type="button"
                        onClick={() => tai(f.token, f.ten_ket_qua || f.ten_file, f.so_thay)}
                        className="px-2 py-1 rounded-lg bg-hds-navy text-hds-gold text-[10px] font-bold flex items-center gap-1"
                      >
                        <Download className="w-3 h-3" /> Tải
                      </button>
                    </>
                  ) : (
                    <span className="text-[10px] text-hds-red">{f.loi || 'không tạo được'}</span>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => setMoBang(moBang === f.ten_file ? null : f.ten_file)}
                  className={`mt-1 text-[10px] font-semibold ${
                    f.so_thay === 0 ? 'text-hds-red' : 'text-hds-navy dark:text-blue-300'
                  } hover:underline`}
                >
                  {f.so_thay === 0
                    ? '⚠ Chưa thay được chỗ nào — vẫn là hồ sơ khách cũ'
                    : `Đã thay ${f.so_thay} chỗ — xem bảng đối chiếu`}
                </button>
                {moBang === f.ten_file && (
                  <div className="mt-1.5 space-y-1">
                    {f.da_thay.map((x, i) => (
                      <p key={i} className="text-[10px] text-slate-600 dark:text-slate-300">
                        «{x.cu}» <ArrowRight className="w-3 h-3 inline" />{' '}
                        <b>{x.moi}</b> ({x.so_cho} chỗ)
                      </p>
                    ))}
                    {f.khong_thay.map((x, i) => (
                      <p key={`k${i}`} className="text-[10px] text-amber-700 dark:text-amber-300">
                        bỏ «{String(x.cu).slice(0, 60)}»: {x.ly_do}
                      </p>
                    ))}
                    {!f.da_thay.length && !f.khong_thay.length && (
                      <p className="text-[10px] text-slate-500">Không có chỗ nào được đề xuất thay.</p>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>

          {/* THANH LƯU — dính đáy, giống panel bộ mẫu. */}
          <div className="sticky bottom-0 -mx-1 px-1 pt-2 pb-2 bg-white/95 dark:bg-slate-900/95 backdrop-blur border-t border-slate-200 dark:border-slate-800">
            <div className="flex flex-wrap items-center gap-2">
              <input
                value={tenLuu}
                onChange={(e) => {
                  setTenLuu(e.target.value);
                  setDaLuu(false);
                }}
                placeholder="Tên hồ sơ để tìm lại (ví dụ: Khách mới — Công ty An Phát)"
                className="flex-1 min-w-[180px] px-2.5 py-2 rounded-xl border border-slate-300 dark:border-slate-700 dark:bg-slate-900 text-[11px] outline-none focus:ring-2 focus:ring-hds-blue"
              />
              <button
                type="button"
                onClick={luuLai}
                disabled={luuBusy}
                className="px-3 py-2 rounded-xl bg-hds-navy text-hds-gold text-[11px] font-bold flex items-center gap-1.5 disabled:opacity-50"
                title="Giữ bộ này lại để mở ở cột trái trong 7 ngày"
              >
                {luuBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                {daLuu ? 'Đã lưu · lưu lại' : 'Lưu bộ hồ sơ'}
              </button>
            </div>
            <p className="mt-1 text-[10px] text-slate-500 dark:text-slate-400">
              {daLuu
                ? 'Đã lưu. Mở lại ở cột «Bộ hồ sơ đã điền» bên trái.'
                : 'Lưu để mở lại ở cột trái trong 7 ngày; đóng cửa sổ mà chưa lưu là mất dấu bộ này.'}
            </p>
          </div>

          <p className="text-[10px] text-slate-500 dark:text-slate-400">
            File kết quả là <b>của riêng bạn</b> và <b>tự xoá sau 7 ngày</b>, không vào kho tri
            thức. Hồ sơ dựng theo bản của khách khác — <b>rà toàn văn</b> để chắc chắn không còn
            sót tên, số giấy tờ hay điều khoản riêng của khách cũ.
          </p>
        </div>
      )}

      {xem && (
        <div
          className="fixed inset-0 z-[60] bg-slate-950/60 backdrop-blur-sm flex items-center justify-center p-4"
          onClick={() => setXem(null)}
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
                <p key={i} className="text-slate-800 dark:text-slate-200">
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
