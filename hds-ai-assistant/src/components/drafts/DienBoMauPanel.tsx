import React, { useEffect, useMemo, useRef, useState } from 'react';
import * as api from '../../api';
import { useApp } from '../../context/AppContext';
import type { BoMau, BoMauChoTrong, BoMauDienResult, BoMauFileDaDien } from '../../types';
import {
  AlertTriangle,
  Check,
  CheckSquare,
  Download,
  Eye,
  FileDown,
  FileText,
  Loader2,
  Package,
  Search,
  Sparkles,
  Square,
  Upload,
  X,
} from 'lucide-react';

/**
 * Điền CẢ BỘ HỒ SƠ từ một tờ khai (18/09/2026).
 *
 * Ba bước đúng như nhân viên làm tay: tải tờ khai → điền → tải lên. Máy đối
 * chiếu mã chỗ trống {{…}} rồi điền vào từng file .docx của bộ, giữ nguyên
 * định dạng gốc, và cho XEM NHANH ngay tại chỗ trước khi tải về.
 *
 * Nhận cả file "tổng hợp thông tin" có sẵn trong bộ (nhân viên gõ đè lên chỗ
 * trống) và hồ sơ rời (CCCD, giấy phép) — hồ sơ rời chỉ dùng cho bước AI đoán
 * các ô còn trống, và giá trị AI đoán luôn mang cờ ⚠.
 */
interface Props {
  bo: BoMau;
  /** Đóng panel (nút Huỷ của modal cha). */
  onClose?: () => void;
}

const DINH_DANG = '.docx,.pdf,.doc,.txt,.md,.jpg,.jpeg,.png,.webp,.tif,.tiff,.bmp';

const CACH_DOC: Record<string, string> = {
  to_khai: 'đọc như TỜ KHAI (bảng mã chỗ trống → giá trị)',
  ban_da_dien: 'đọc như BẢN SAO FILE MẪU đã gõ đè',
  van_ban: 'chỉ lấy nội dung làm ngữ cảnh cho AI',
  loi: 'không đọc được',
};

export const DienBoMauPanel: React.FC<Props> = ({ bo, onClose }) => {
  const { showToast } = useApp();
  const [choTrong, setChoTrong] = useState<BoMauChoTrong[]>([]);
  const [loiMau, setLoiMau] = useState<Array<{ ten_file: string; loi: string }>>([]);
  const [dangNap, setDangNap] = useState(true);
  const [files, setFiles] = useState<File[]>([]);
  const [fileIds, setFileIds] = useState<number[]>([]);        // rỗng = cả bộ
  const [giaTri, setGiaTri] = useState<Record<string, string>>({});
  const [dungAi, setDungAi] = useState(true);
  const [timO, setTimO] = useState('');
  const [moGoTay, setMoGoTay] = useState(false);
  const [busy, setBusy] = useState(false);
  const [tienTrinh, setTienTrinh] = useState(0);
  const [ketQua, setKetQua] = useState<BoMauDienResult | null>(null);
  const [xem, setXem] = useState<{ ten: string; doan: string[]; cat_bot: boolean } | null>(null);
  const [xemBusy, setXemBusy] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    let alive = true;
    setDangNap(true);
    api
      .getBoMauChoTrong(bo.id)
      .then((res) => {
        if (!alive) return;
        setChoTrong(Array.isArray(res.items) ? res.items : []);
        setLoiMau(Array.isArray(res.loi_mau) ? res.loi_mau : []);
      })
      .catch((err: any) => {
        if (alive) showToast(err?.message || 'Không đọc được chỗ trống của bộ.', 'error');
      })
      .finally(() => {
        if (alive) setDangNap(false);
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bo.id]);

  const caBo = fileIds.length === 0;
  const daChon = (id: number) => caBo || fileIds.includes(id);
  const toggleFile = (id: number) => {
    const tatCa = bo.files.map((f) => f.id);
    const hienTai = caBo ? tatCa : fileIds;
    const tiep = hienTai.includes(id) ? hienTai.filter((x) => x !== id) : [...hienTai, id];
    setFileIds(tiep.length === tatCa.length ? [] : tiep);
  };
  const soFileChon = caBo ? bo.files.length : fileIds.length;

  const oLoc = useMemo(() => {
    const q = timO.trim().toLowerCase();
    if (!q) return choTrong;
    return choTrong.filter(
      (o) => o.literal.toLowerCase().includes(q) || (o.goi_y || '').toLowerCase().includes(q)
    );
  }, [choTrong, timO]);

  const soOGoTay = Object.values(giaTri).filter((v) => (v || '').trim()).length;

  const themFile = (ds: FileList | null) => {
    if (!ds || !ds.length) return;
    setFiles((truoc) => {
      const gop = [...truoc];
      Array.from(ds).forEach((f) => {
        if (!gop.some((x) => x.name === f.name && x.size === f.size)) gop.push(f);
      });
      return gop.slice(0, 10);
    });
  };

  const taiToKhai = async () => {
    try {
      await api.downloadBoMauToKhai(bo.id, `To khai - ${bo.ten}.docx`);
    } catch (err: any) {
      showToast(err?.message || 'Không tải được tờ khai.', 'error');
    }
  };

  const chay = async () => {
    if (busy) return;
    setBusy(true);
    setTienTrinh(0);
    try {
      const res = await api.dienBoMau({
        boId: bo.id,
        files,
        fileIds,
        giaTri: Object.fromEntries(
          Object.entries(giaTri).filter(([, v]) => (v || '').trim())
        ),
        dungAi,
        onProgress: setTienTrinh,
      });
      setKetQua(res);
      const xong = (res.files || []).filter((f) => f.token).length;
      showToast(`Đã điền ${xong}/${(res.files || []).length} file.`, xong ? 'success' : 'error');
    } catch (err: any) {
      showToast(err?.message || 'Không điền được bộ hồ sơ.', 'error');
    } finally {
      setBusy(false);
      setTienTrinh(0);
    }
  };

  const xemNhanh = async (f: BoMauFileDaDien) => {
    if (!f.token) return;
    setXemBusy(f.token);
    try {
      const res = await api.xemTemplateFill(f.token);
      setXem({ ten: res.ten_file || f.ten_file, doan: res.doan || [], cat_bot: !!res.cat_bot });
    } catch (err: any) {
      showToast(err?.message || 'Không xem nhanh được file này.', 'error');
    } finally {
      setXemBusy(null);
    }
  };

  const taiFile = async (token: string | null, ten: string) => {
    if (!token) return;
    try {
      await api.downloadTemplateFill(token, ten);
    } catch (err: any) {
      showToast(err?.message || 'Không tải được file.', 'error');
    }
  };

  const xemPdf = async (token: string | null) => {
    if (!token) return;
    try {
      await api.previewTemplateFill(token);
    } catch (err: any) {
      // 409 = máy chủ chưa có LibreOffice; xem nhanh dạng chữ vẫn dùng được.
      showToast(err?.message || 'Không mở được bản PDF.', 'error');
    }
  };

  const soDaDien = ketQua?.da_dien?.length || 0;
  const soThieu = ketQua?.con_thieu?.length || 0;

  return (
    <div className="space-y-4">
      <div className="p-3 rounded-xl border border-hds-navy/30 dark:border-blue-900 bg-hds-soft dark:bg-slate-800/60">
        <p className="text-xs font-bold text-hds-navy dark:text-blue-200 flex items-center gap-1.5">
          <Package className="w-4 h-4 text-hds-gold" /> Điền bộ hồ sơ «{bo.ten}» — {bo.files.length} file .docx
        </p>
        <p className="mt-1 text-[11px] leading-relaxed text-slate-600 dark:text-slate-300">
          Tải <b>tờ khai thông tin</b> về, điền một lần rồi tải lên — máy chép giá trị vào
          đúng chỗ trống của <b>từng file</b> trong bộ và giữ nguyên định dạng Word. Tải
          lên chính file “tổng hợp thông tin” của bộ (đã gõ đè lên các ô) cũng được.
        </p>
      </div>

      {/* BƯỚC 1 — tờ khai */}
      <div className="p-3 rounded-xl border border-slate-200 dark:border-slate-700">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs font-bold text-slate-700 dark:text-slate-300">
              Bước 1 · Tờ khai thông tin
            </p>
            <p className="mt-0.5 text-[10px] text-slate-500 dark:text-slate-400">
              {dangNap
                ? 'Đang đọc các ô thông tin của bộ…'
                : choTrong.length
                ? `Bộ này có ${choTrong.length} ô thông tin (các chỗ trống trùng nhau đã gộp làm một).`
                : 'Các file mẫu trong bộ chưa có chỗ trống dạng {{TÊN_Ô}} — hãy mở file Word, đặt chỗ trống rồi tải lại vào bộ.'}
            </p>
          </div>
          <button
            type="button"
            onClick={taiToKhai}
            disabled={dangNap || !choTrong.length}
            className="shrink-0 px-3 py-2 rounded-xl border border-hds-navy text-hds-navy dark:text-blue-300 dark:border-blue-700 text-[11px] font-bold flex items-center gap-1.5 hover:bg-hds-soft dark:hover:bg-slate-800 disabled:opacity-40"
          >
            <FileDown className="w-3.5 h-3.5" /> Tải tờ khai (.docx)
          </button>
        </div>
        {loiMau.length > 0 && (
          <p className="mt-2 text-[10px] text-hds-red">
            Không mở được: {loiMau.map((l) => `«${l.ten_file}» (${l.loi})`).join('; ')}
          </p>
        )}
      </div>

      {/* BƯỚC 2 — tải lên */}
      <div className="p-3 rounded-xl border border-slate-200 dark:border-slate-700">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs font-bold text-slate-700 dark:text-slate-300">
              Bước 2 · Tải tờ khai đã điền lên
            </p>
            <p className="mt-0.5 text-[10px] leading-relaxed text-slate-500 dark:text-slate-400">
              Nhận tối đa 10 file: tờ khai đã điền, bản sao file mẫu đã gõ đè, hoặc hồ sơ rời
              (CCCD, giấy phép, CV) để AI đoán nốt các ô còn trống.
            </p>
          </div>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept={DINH_DANG}
            className="sr-only"
            onChange={(e) => {
              themFile(e.target.files);
              e.target.value = '';
            }}
          />
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            disabled={busy}
            className="shrink-0 px-3 py-2 rounded-xl bg-hds-navy text-hds-gold text-[11px] font-bold flex items-center gap-1.5 hover:bg-hds-navy-light disabled:opacity-40"
          >
            <Upload className="w-3.5 h-3.5" /> Chọn file
          </button>
        </div>
        {files.length > 0 && (
          <ul className="mt-2 space-y-1">
            {files.map((f) => (
              <li
                key={`${f.name}-${f.size}`}
                className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-slate-50 dark:bg-slate-800 text-[11px]"
              >
                <FileText className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                <span className="flex-1 truncate">{f.name}</span>
                <span className="text-slate-400">{Math.max(1, Math.round(f.size / 1024))} KB</span>
                <button
                  type="button"
                  aria-label={`Bỏ ${f.name}`}
                  onClick={() => setFiles((truoc) => truoc.filter((x) => x !== f))}
                  className="text-slate-400 hover:text-hds-red"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}
        <label className="mt-2 flex items-start gap-2 text-[11px] text-slate-600 dark:text-slate-300 cursor-pointer">
          <input
            type="checkbox"
            checked={dungAi}
            onChange={(e) => setDungAi(e.target.checked)}
            className="mt-0.5"
          />
          <span>
            <b>Cho AI đoán các ô còn trống</b> từ hồ sơ rời đã tải lên. Giá trị AI đoán được
            đánh dấu ⚠ trong bảng đối chiếu — vẫn phải soát lại. Bỏ chọn nếu muốn hoàn toàn
            tất định (chỉ lấy đúng những gì đã gõ trong tờ khai).
          </span>
        </label>
      </div>

      {/* Chọn file trong bộ + gõ tay */}
      <div className="p-3 rounded-xl border border-slate-200 dark:border-slate-700">
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs font-bold text-slate-700 dark:text-slate-300">
            File cần điền ({soFileChon}/{bo.files.length})
          </p>
          <button
            type="button"
            onClick={() => setFileIds([])}
            className="text-[10px] text-hds-navy dark:text-blue-300 hover:underline"
          >
            Chọn cả bộ
          </button>
        </div>
        <ul className="mt-1.5 max-h-40 overflow-y-auto space-y-0.5">
          {bo.files.map((f) => (
            <li key={f.id}>
              <button
                type="button"
                onClick={() => toggleFile(f.id)}
                className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-[11px] hover:bg-slate-50 dark:hover:bg-slate-800 text-left"
              >
                {daChon(f.id) ? (
                  <CheckSquare className="w-3.5 h-3.5 text-hds-navy dark:text-blue-300 shrink-0" />
                ) : (
                  <Square className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                )}
                <span className="flex-1 truncate">{f.ten_file}</span>
                <span className="text-[10px] text-slate-400 shrink-0">
                  {f.so_placeholder > 0 ? `${f.so_placeholder} chỗ trống` : 'không có {{…}}'}
                </span>
              </button>
            </li>
          ))}
        </ul>

        <button
          type="button"
          onClick={() => setMoGoTay((v) => !v)}
          className="mt-2 text-[11px] font-semibold text-hds-navy dark:text-blue-300 hover:underline"
        >
          {moGoTay ? 'Ẩn phần gõ tay' : `Gõ tay từng ô (${choTrong.length} ô${soOGoTay ? `, đã gõ ${soOGoTay}` : ''})`}
        </button>
        {moGoTay && (
          <div className="mt-2">
            <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-slate-50 dark:bg-slate-800">
              <Search className="w-3.5 h-3.5 text-slate-400" />
              <input
                value={timO}
                onChange={(e) => setTimO(e.target.value)}
                placeholder="Tìm ô theo mã hoặc nội dung…"
                className="flex-1 bg-transparent text-[11px] outline-none"
              />
            </div>
            <div className="mt-2 max-h-64 overflow-y-auto grid sm:grid-cols-2 gap-2">
              {oLoc.map((o) => (
                <label key={o.khoa} className="space-y-1">
                  <span className="block text-[10px] font-semibold text-slate-600 dark:text-slate-300 truncate">
                    {o.goi_y || o.literal}
                    <span className="ml-1 font-mono text-slate-400">{o.literal}</span>
                  </span>
                  <input
                    value={giaTri[o.khoa] ?? ''}
                    onChange={(e) => setGiaTri((truoc) => ({ ...truoc, [o.khoa]: e.target.value }))}
                    className="w-full px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 dark:bg-slate-900 text-[11px] outline-none focus:ring-2 focus:ring-hds-blue"
                  />
                </label>
              ))}
              {!oLoc.length && (
                <p className="text-[11px] text-slate-500 col-span-2">Không có ô nào khớp.</p>
              )}
            </div>
          </div>
        )}
      </div>

      <button
        type="button"
        onClick={chay}
        disabled={busy || !bo.files.length || soFileChon === 0}
        className="w-full px-4 py-2.5 rounded-xl bg-hds-navy text-hds-gold text-xs font-bold flex items-center justify-center gap-2 disabled:opacity-50"
      >
        {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
        {busy
          ? tienTrinh > 0 && tienTrinh < 100
            ? `Đang tải lên ${tienTrinh}%…`
            : 'Đang điền từng file…'
          : `Điền ${soFileChon} file của bộ`}
      </button>

      {/* KẾT QUẢ */}
      {ketQua && (
        <div className="space-y-3">
          <div className="p-3 rounded-xl border border-emerald-200 dark:border-emerald-900 bg-emerald-50/60 dark:bg-emerald-950/30">
            <p className="text-xs font-bold text-emerald-900 dark:text-emerald-200">
              Đã điền {(ketQua.files || []).filter((f) => f.token).length}/{(ketQua.files || []).length} file
              · {soDaDien}/{ketQua.so_o} ô có dữ liệu
              {soThieu > 0 && ` · còn thiếu ${soThieu} ô`}
            </p>
            {(ketQua.doc_file || []).length > 0 && (
              <ul className="mt-1.5 space-y-0.5">
                {ketQua.doc_file.map((d, i) => (
                  <li key={`${d.ten_file}-${i}`} className="text-[10px] text-emerald-900/80 dark:text-emerald-200/80">
                    «{d.ten_file}»: {CACH_DOC[d.cach] || d.cach}
                    {d.cach === 'ban_da_dien' && d.mau ? ` — khớp mẫu «${d.mau}»` : ''}
                    {d.so_o ? ` → lấy được ${d.so_o} ô` : ''}
                    {d.loi ? ` — ${d.loi}` : ''}
                  </li>
                ))}
              </ul>
            )}
            {ketQua.gia_tri_thua > 0 && (
              <p className="mt-1 text-[10px] text-amber-800 dark:text-amber-300">
                Bỏ qua {ketQua.gia_tri_thua} ô không thuộc bộ này (có thể là tờ khai của bộ khác).
              </p>
            )}
            {ketQua.ghi_chu_ai && (
              <p className="mt-1 text-[10px] text-amber-800 dark:text-amber-300">
                Ghi chú của AI: {ketQua.ghi_chu_ai}
              </p>
            )}
            {(ketQua.loi_tai_len || []).map((l) => (
              <p key={l.ten_file} className="mt-1 text-[10px] text-hds-red">
                «{l.ten_file}»: {l.loi}
              </p>
            ))}
          </div>

          {ketQua.zip_token && (
            <button
              type="button"
              onClick={() => taiFile(ketQua.zip_token, `${bo.ten} - da dien.zip`)}
              className="w-full px-3 py-2 rounded-xl border border-hds-navy text-hds-navy dark:text-blue-300 dark:border-blue-700 text-[11px] font-bold flex items-center justify-center gap-1.5 hover:bg-hds-soft dark:hover:bg-slate-800"
            >
              <Package className="w-3.5 h-3.5" /> Tải cả bộ (.zip)
            </button>
          )}

          <ul className="space-y-1.5">
            {(ketQua.files || []).map((f) => (
              <li
                key={f.file_id}
                className="p-2.5 rounded-xl border border-slate-200 dark:border-slate-700"
              >
                <div className="flex items-center gap-2">
                  <FileText className="w-4 h-4 text-slate-400 shrink-0" />
                  <span className="flex-1 text-[11px] font-semibold truncate">{f.ten_file}</span>
                  {f.token ? (
                    <>
                      <button
                        type="button"
                        onClick={() => xemNhanh(f)}
                        className="px-2 py-1 rounded-lg border border-slate-300 dark:border-slate-700 text-[10px] font-bold flex items-center gap-1 hover:bg-slate-50 dark:hover:bg-slate-800"
                        title="Xem nhanh nội dung ngay tại đây"
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
                        onClick={() => xemPdf(f.token)}
                        className="px-2 py-1 rounded-lg border border-slate-300 dark:border-slate-700 text-[10px] font-bold hover:bg-slate-50 dark:hover:bg-slate-800"
                        title="Mở bản PDF giữ nguyên định dạng Word (cần LibreOffice trên máy chủ)"
                      >
                        PDF
                      </button>
                      <button
                        type="button"
                        onClick={() => taiFile(f.token, f.ten_ket_qua || f.ten_file)}
                        className="px-2 py-1 rounded-lg bg-hds-navy text-hds-gold text-[10px] font-bold flex items-center gap-1"
                      >
                        <Download className="w-3 h-3" /> Tải
                      </button>
                    </>
                  ) : (
                    <span className="text-[10px] text-hds-red">{f.loi || 'không tạo được'}</span>
                  )}
                </div>
                {f.token && (
                  <p className="mt-1 text-[10px] text-slate-500 dark:text-slate-400">
                    Đã thay {f.so_thay} chỗ
                    {f.con_trong.length > 0 && (
                      <>
                        {' · '}
                        <span className="text-amber-700 dark:text-amber-300">
                          còn trống: {f.con_trong.slice(0, 6).join(', ')}
                          {f.con_trong.length > 6 ? ` … (+${f.con_trong.length - 6})` : ''}
                        </span>
                      </>
                    )}
                  </p>
                )}
              </li>
            ))}
          </ul>

          {soThieu > 0 && (
            <div className="p-3 rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50/60 dark:bg-amber-950/30">
              <p className="text-xs font-bold text-amber-900 dark:text-amber-200 flex items-center gap-1.5">
                <AlertTriangle className="w-4 h-4" /> {soThieu} ô chưa có dữ liệu — điền tại đây rồi
                bấm lại
              </p>
              <div className="mt-2 max-h-56 overflow-y-auto grid sm:grid-cols-2 gap-2">
                {ketQua.con_thieu.map((o) => (
                  <label key={o.khoa} className="space-y-1">
                    <span className="block text-[10px] font-semibold text-amber-900 dark:text-amber-200 truncate">
                      {o.goi_y || o.literal}
                      <span className="ml-1 font-mono opacity-70">{o.literal}</span>
                    </span>
                    <input
                      value={giaTri[o.khoa] ?? ''}
                      onChange={(e) => setGiaTri((truoc) => ({ ...truoc, [o.khoa]: e.target.value }))}
                      className="w-full px-2 py-1.5 rounded-lg border border-amber-200 dark:border-amber-800 dark:bg-slate-900 text-[11px] outline-none focus:ring-2 focus:ring-hds-blue"
                    />
                  </label>
                ))}
              </div>
              <button
                type="button"
                onClick={chay}
                disabled={busy || soOGoTay === 0}
                className="mt-2 px-3 py-2 rounded-xl bg-hds-navy text-hds-gold text-[11px] font-bold flex items-center gap-1.5 disabled:opacity-40"
              >
                {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                Điền lại với thông tin vừa bổ sung
              </button>
            </div>
          )}

          <p className="text-[10px] text-slate-500 dark:text-slate-400">
            Văn bản sẽ gửi ra ngoài — hãy <b>rà toàn văn</b> từng file (tên bên, con số, ngày
            tháng, điều khoản) trước khi dùng. File kết quả tự xoá sau 24 giờ, không vào kho.
          </p>
        </div>
      )}

      {onClose && (
        <div className="flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            Đóng
          </button>
        </div>
      )}

      {/* XEM NHANH */}
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
            <div className="p-3 border-t border-slate-200 dark:border-slate-800 text-[10px] text-slate-500">
              Dòng màu vàng là chỗ trống <span className="font-mono">{'{{…}}'}</span> chưa có dữ liệu.
              Bản xem nhanh chỉ hiển thị chữ — bấm <b>PDF</b> để xem đúng định dạng Word.
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
