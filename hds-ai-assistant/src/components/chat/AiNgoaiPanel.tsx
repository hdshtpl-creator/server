import React, { useEffect, useMemo, useRef, useState } from 'react';
import { MessageMarkdown, CITE_RE } from './MessageMarkdown';
import { SourcePanel } from './SourcePanel';
import * as api from '../../api';
import type {
  AiKhacKetQua,
  AiNgoaiCauHinh,
  AiNgoaiLoc,
  AiSoatKetQua,
  ChatMessage,
  Source,
} from '../../types';
import {
  ShieldCheck,
  ShieldAlert,
  ShieldX,
  ShieldQuestion,
  Lock,
  Loader2,
  RefreshCw,
  Shuffle,
  ChevronDown,
  ChevronUp,
  Square,
  AlertTriangle,
} from 'lucide-react';

/**
 * ChatGPT làm việc SONG SONG với Qwen (hds-ai/app/ai_ngoai.py):
 *   · SOÁT đầu ra — huy hiệu "ChatGPT: ổn / cần xem lại / có sai sót" kèm
 *     từng vấn đề; chế độ tự động thì soát ngay khi câu trả lời viết xong.
 *   · "XEM CÂU TRẢ LỜI KHÁC" — model ngoài trả lời lại cùng câu hỏi, cùng
 *     quyền đọc tài liệu, hiện ngay bên dưới để luật sư so sánh.
 *
 * Nút chỉ hiện khi quản trị đã bật VÀ máy chủ có khoá API (GET
 * /ai-ngoai/cau-hinh). Nút hiện THƯỜNG TRỰC — không ẩn chờ rê chuột (nút ẩn
 * khi rê chuột = người dùng báo "không có nút").
 */

const fmtSec = (ms?: number) =>
  typeof ms !== 'number' ? '' : ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
const fmtUsd = (v?: number | null) =>
  typeof v !== 'number' ? '' : `~$${v < 0.01 ? v.toFixed(4) : v.toFixed(3)}`;

function useAiNgoaiCauHinh(): AiNgoaiCauHinh | null {
  const [cfg, setCfg] = useState<AiNgoaiCauHinh | null>(null);
  useEffect(() => {
    let song = true;
    api.getAiNgoaiCauHinh().then((c) => {
      if (song) setCfg(c);
    });
    return () => {
      song = false;
    };
  }, []);
  return cfg;
}

const MUC_DO: Record<string, { nhan: string; cls: string }> = {
  cao: {
    nhan: 'Nghiêm trọng',
    cls: 'bg-red-100 dark:bg-red-950/60 text-red-800 dark:text-red-300 border-red-200 dark:border-red-800',
  },
  vua: {
    nhan: 'Cần sửa',
    cls: 'bg-amber-100 dark:bg-amber-950/60 text-amber-800 dark:text-amber-300 border-amber-200 dark:border-amber-800',
  },
  thap: {
    nhan: 'Góp ý',
    cls: 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-700',
  },
};

function nhanSoat(kq: AiSoatKetQua, tenNgan: string) {
  if (kq.trang_thai === 'khong_gui') {
    return {
      icon: <Lock className="w-3.5 h-3.5" />,
      nhan: `Không gửi ${tenNgan} soát`,
      cls: 'bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-700',
    };
  }
  const n = (kq.van_de || []).length;
  switch (kq.ket_luan) {
    case 'on':
      return {
        icon: <ShieldCheck className="w-3.5 h-3.5" />,
        nhan: `${tenNgan}: ổn`,
        cls: 'bg-emerald-50 dark:bg-emerald-950/50 text-emerald-800 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800',
      };
    case 'can_xem_lai':
      return {
        icon: <ShieldAlert className="w-3.5 h-3.5" />,
        nhan: `${tenNgan}: cần xem lại${n ? ` (${n} điểm)` : ''}`,
        cls: 'bg-amber-50 dark:bg-amber-950/50 text-amber-800 dark:text-amber-300 border-amber-200 dark:border-amber-800',
      };
    case 'co_sai_sot':
      return {
        icon: <ShieldX className="w-3.5 h-3.5" />,
        nhan: `${tenNgan}: có sai sót${n ? ` (${n} điểm)` : ''}`,
        cls: 'bg-red-50 dark:bg-red-950/50 text-red-800 dark:text-red-300 border-red-200 dark:border-red-800',
      };
    default:
      return {
        icon: <ShieldQuestion className="w-3.5 h-3.5" />,
        nhan: `${tenNgan}: xem nhận xét`,
        cls: 'bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-700',
      };
  }
}

/** "3 file đính kèm, 1 tài liệu nội bộ" — thứ KHÔNG được gửi ra ngoài. */
function moTaLoc(loc?: AiNgoaiLoc | null): string {
  if (!loc || !loc.tong) return '';
  const phan: string[] = [];
  if (loc.ho_so_khach) phan.push(`${loc.ho_so_khach} đoạn hồ sơ khách`);
  if (loc.tai_lieu_noi_bo) phan.push(`${loc.tai_lieu_noi_bo} đoạn tài liệu nội bộ`);
  if (loc.dinh_kem) phan.push(`${loc.dinh_kem} đoạn file đính kèm`);
  if (loc.cong_no) phan.push(`${loc.cong_no} đoạn công nợ`);
  if (loc.du_lieu_cong_ty) phan.push('dữ liệu công ty');
  return phan.join(', ');
}

/** Tên ngắn cho huy hiệu: "ChatGPT (gpt-5-mini)" → "ChatGPT". */
const tenNgan = (ten?: string) => (ten || 'ChatGPT').replace(/\s*\(.*\)\s*$/, '') || 'ChatGPT';

interface Props {
  message: ChatMessage;
  onPreview: (docId: number) => void;
  onDownload: (docId: number, title: string) => void;
}

export const AiNgoaiPanel: React.FC<Props> = ({ message, onPreview, onDownload }) => {
  const cfg = useAiNgoaiCauHinh();
  const msgId = message.serverMessageId as number;

  // ----- SOÁT -----
  const [soat, setSoat] = useState<AiSoatKetQua | null>(message.ai_soat ?? null);
  const [soatDang, setSoatDang] = useState(false);
  const [soatLoi, setSoatLoi] = useState<string | null>(null);
  const [soatMo, setSoatMo] = useState(false);
  const daTuSoat = useRef(false);

  const chaySoat = async (lamLai: boolean) => {
    if (soatDang) return;
    setSoatDang(true);
    setSoatLoi(null);
    try {
      const res = await api.aiSoat(msgId, { lamLai });
      setSoat(res.ket_qua);
      // Có vấn đề thì mở sẵn chi tiết — người đọc không phải đoán vì sao vàng/đỏ.
      setSoatMo(res.ket_qua.trang_thai === 'xong' && res.ket_qua.ket_luan !== 'on');
    } catch (err: any) {
      setSoatLoi(err?.message || 'Không soát được câu trả lời này.');
    } finally {
      setSoatDang(false);
    }
  };

  // Soát TỰ ĐỘNG: chỉ câu trả lời vừa viết trong phiên này (không phải mở lại
  // từ lịch sử — id 'h-…'), chỉ một lần, và không soát câu đã bị dừng giữa chừng.
  useEffect(() => {
    if (
      cfg?.soat === 'tu_dong' &&
      typeof msgId === 'number' &&
      !message.isStreaming &&
      !message.id.startsWith('h-') &&
      message.grounding_status !== 'stopped' &&
      !soat &&
      !daTuSoat.current
    ) {
      daTuSoat.current = true;
      void chaySoat(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cfg?.soat, msgId, message.isStreaming]);

  // ----- CÂU TRẢ LỜI KHÁC -----
  const [khac, setKhac] = useState<AiKhacKetQua | null>(message.ai_khac ?? null);
  const [khacText, setKhacText] = useState('');
  const [khacNguon, setKhacNguon] = useState<Source[]>([]);
  const [khacLoc, setKhacLoc] = useState<AiNgoaiLoc | null>(null);
  const [khacStatus, setKhacStatus] = useState('');
  const [khacDang, setKhacDang] = useState(false);
  const [khacLoi, setKhacLoi] = useState<string | null>(null);
  // Đã có từ lịch sử thì thu gọn — mở lại hội thoại dài mà bung hết thì rối.
  const [khacMo, setKhacMo] = useState(false);
  const huyKhac = useRef<AbortController | null>(null);
  const [showNguonKhac, setShowNguonKhac] = useState(false);
  const [focusNguonKhac, setFocusNguonKhac] = useState<number | null>(null);

  useEffect(() => () => huyKhac.current?.abort(), []);

  const chayKhac = async (lamLai: boolean) => {
    if (khacDang) return;
    setKhacMo(true);
    setKhacDang(true);
    setKhacLoi(null);
    setKhacText('');
    setKhacNguon([]);
    setKhacLoc(null);
    setKhacStatus('Đang chuẩn bị…');
    if (lamLai) setKhac(null);
    const ctl = new AbortController();
    huyKhac.current = ctl;
    try {
      const res = await api.cauTraLoiKhac(msgId, { lamLai, signal: ctl.signal }, (evt) => {
        if (evt.type === 'status') setKhacStatus(evt.label);
        else if (evt.type === 'meta') {
          setKhacNguon(evt.sources || []);
          setKhacLoc(evt.loc ?? null);
        } else if (evt.type === 'delta') setKhacText((t) => t + evt.text);
      });
      setKhac(res.ket_qua);
    } catch (err: any) {
      if (err?.code !== api.DUNG_BOI_NGUOI_DUNG) {
        setKhacLoi(err?.message || 'Không lấy được câu trả lời khác.');
      }
    } finally {
      setKhacDang(false);
      setKhacStatus('');
      huyKhac.current = null;
    }
  };

  const textKhac = khac?.trang_thai === 'xong' ? khac.text || '' : khacText;
  const nguonKhac = khac?.trang_thai === 'xong' ? khac.sources || [] : khacNguon;
  const locKhac = khac?.loc ?? khacLoc;
  const validKhac = useMemo(
    () => new Set(nguonKhac.map((s) => s.n).filter((n): n is number => typeof n === 'number')),
    [nguonKhac]
  );
  const citedKhac = useMemo(() => {
    const out = new Set<number>();
    for (const m of textKhac.matchAll(CITE_RE)) out.add(parseInt(m[1], 10));
    return out;
  }, [textKhac]);
  const bamTrichKhac = (n: number) => {
    setShowNguonKhac(true);
    setFocusNguonKhac(n);
    requestAnimationFrame(() => {
      document
        .getElementById(`msg-${message.id}-khac-src-${n}`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
    window.setTimeout(() => setFocusNguonKhac(null), 2500);
  };

  const coSoat = cfg?.soat && cfg.soat !== 'tat';
  const coKhac = Boolean(cfg?.khac);
  // Kết quả đã lưu vẫn hiện kể cả khi quản trị vừa tắt tính năng.
  if (!coSoat && !coKhac && !soat && !khac) return null;

  const ten = tenNgan(cfg?.ten_soat || soat?.ten_model);
  const nhan = soat ? nhanSoat(soat, ten) : null;
  const tenKhac = khac?.ten_model || cfg?.ten_khac || 'ChatGPT';

  const nutCls =
    'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-[11px] font-semibold transition-colors disabled:opacity-60';

  return (
    <div className="space-y-2 pt-1">
      {/* Hàng nút / huy hiệu — luôn hiện */}
      <div className="flex flex-wrap items-center gap-1.5">
        {soatDang ? (
          <span className={`${nutCls} border-slate-200 dark:border-slate-700 text-slate-500 dark:text-slate-400`}>
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            {ten} đang soát…
          </span>
        ) : nhan ? (
          <button
            type="button"
            onClick={() => setSoatMo((v) => !v)}
            className={`${nutCls} ${nhan.cls}`}
            title="Bấm để xem nhận xét"
          >
            {nhan.icon}
            {nhan.nhan}
            {soatMo ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>
        ) : coSoat ? (
          <button
            type="button"
            onClick={() => void chaySoat(false)}
            className={`${nutCls} border-slate-300 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:border-hds-navy hover:text-hds-navy dark:hover:text-blue-300`}
            title={`Gửi câu hỏi, câu trả lời và các nguồn được phép cho ${cfg?.ten_soat || 'ChatGPT'} soát`}
          >
            <ShieldCheck className="w-3.5 h-3.5" />
            Soát bằng {ten}
          </button>
        ) : null}

        {coKhac && !khacDang && !(khac || khacText) && (
          <button
            type="button"
            onClick={() => void chayKhac(false)}
            className={`${nutCls} border-slate-300 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:border-hds-navy hover:text-hds-navy dark:hover:text-blue-300`}
            title={`${cfg?.ten_khac || 'ChatGPT'} trả lời lại cùng câu hỏi`}
          >
            <Shuffle className="w-3.5 h-3.5" />
            Xem câu trả lời khác
          </button>
        )}
        {(khac || khacText || khacDang) && !khacMo && (
          <button
            type="button"
            onClick={() => setKhacMo(true)}
            className={`${nutCls} border-indigo-200 dark:border-indigo-800 text-indigo-700 dark:text-indigo-300 bg-indigo-50/60 dark:bg-indigo-950/40`}
          >
            <Shuffle className="w-3.5 h-3.5" />
            Câu trả lời khác ({tenNgan(tenKhac)})
            <ChevronDown className="w-3 h-3" />
          </button>
        )}
      </div>

      {soatLoi && (
        <div className="flex items-start gap-1.5 text-[11px] text-red-700 dark:text-red-300">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-px" />
          <span>{soatLoi}</span>
          <button
            type="button"
            onClick={() => void chaySoat(false)}
            className="underline font-semibold shrink-0"
          >
            Thử lại
          </button>
        </div>
      )}

      {/* Chi tiết soát */}
      {soat && soatMo && (
        <div className="text-xs rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/70 dark:bg-slate-800/50 p-3 space-y-2">
          {soat.trang_thai === 'khong_gui' ? (
            <p className="text-slate-600 dark:text-slate-300 leading-relaxed">{soat.ly_do}</p>
          ) : (
            <>
              {soat.tom_tat && (
                <p className="text-slate-700 dark:text-slate-200 leading-relaxed">{soat.tom_tat}</p>
              )}
              {(soat.van_de || []).length > 0 && (
                <ul className="space-y-1.5">
                  {(soat.van_de || []).map((v, i) => {
                    const md = MUC_DO[v.muc_do] || MUC_DO.vua;
                    return (
                      <li key={i} className="flex items-start gap-2">
                        <span
                          className={`shrink-0 mt-px px-1.5 py-0.5 rounded border text-[10px] font-bold ${md.cls}`}
                        >
                          {md.nhan}
                        </span>
                        <span className="text-slate-700 dark:text-slate-200 leading-relaxed">
                          {v.noi_dung}
                          {v.goi_y && (
                            <span className="block text-slate-500 dark:text-slate-400 mt-0.5">
                              → {v.goi_y}
                            </span>
                          )}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </>
          )}
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 pt-1.5 border-t border-slate-200 dark:border-slate-700 text-[10px] text-slate-500 dark:text-slate-400">
            <span>{soat.ten_model || soat.model}</span>
            {soat.ms ? <span>· {fmtSec(soat.ms)}</span> : null}
            {soat.cost_usd != null && <span>· {fmtUsd(soat.cost_usd)}</span>}
            {soat.nguon_gui != null && soat.trang_thai === 'xong' && (
              <span>
                · gửi kèm {soat.nguon_gui} nguồn
                {soat.nguon_bo ? `, giữ lại ${soat.nguon_bo} nguồn nội bộ` : ''}
              </span>
            )}
            {soat.da_che ? <span>· đã che {soat.da_che} chỗ định danh</span> : null}
            <span className="flex-1" />
            {coSoat && (
              <button
                type="button"
                onClick={() => void chaySoat(true)}
                disabled={soatDang}
                className="inline-flex items-center gap-1 font-semibold hover:text-hds-navy dark:hover:text-blue-300"
              >
                <RefreshCw className="w-3 h-3" />
                Soát lại
              </button>
            )}
          </div>
          <p className="text-[10px] italic text-slate-400 dark:text-slate-500">
            Nhận xét của model ngoài để tham khảo — luật sư đối chiếu nguồn trước khi dùng.
          </p>
        </div>
      )}

      {/* Câu trả lời khác */}
      {khacMo && (khac || khacText || khacDang || khacLoi) && (
        <div className="rounded-xl border border-indigo-200 dark:border-indigo-900 bg-indigo-50/40 dark:bg-indigo-950/20 p-3 space-y-2">
          <div className="flex items-center justify-between gap-2 text-xs">
            <span className="flex items-center gap-1.5 font-bold text-indigo-900 dark:text-indigo-200 min-w-0">
              <Shuffle className="w-3.5 h-3.5 shrink-0" />
              <span className="truncate">Câu trả lời khác — {tenKhac}</span>
            </span>
            <span className="flex items-center gap-2 shrink-0 text-[11px]">
              {khacDang ? (
                <button
                  type="button"
                  onClick={() => huyKhac.current?.abort()}
                  className="inline-flex items-center gap-1 font-semibold text-slate-600 dark:text-slate-300 hover:text-hds-red"
                >
                  <Square className="w-3 h-3" />
                  Dừng
                </button>
              ) : (
                coKhac && (
                  <button
                    type="button"
                    onClick={() => void chayKhac(true)}
                    className="inline-flex items-center gap-1 font-semibold text-slate-600 dark:text-slate-300 hover:text-hds-navy dark:hover:text-blue-300"
                  >
                    <RefreshCw className="w-3 h-3" />
                    Hỏi lại
                  </button>
                )
              )}
              <button
                type="button"
                onClick={() => setKhacMo(false)}
                className="inline-flex items-center gap-1 font-semibold text-slate-600 dark:text-slate-300 hover:text-hds-navy dark:hover:text-blue-300"
              >
                <ChevronUp className="w-3 h-3" />
                Thu gọn
              </button>
            </span>
          </div>

          {khac && khac.trang_thai !== 'xong' ? (
            <p className="text-xs text-slate-600 dark:text-slate-300 flex items-start gap-1.5 leading-relaxed">
              <Lock className="w-3.5 h-3.5 shrink-0 mt-px" />
              {khac.ly_do}
            </p>
          ) : (
            <>
              {!textKhac && khacDang ? (
                <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  {khacStatus || 'Đang chuẩn bị…'}
                </div>
              ) : textKhac ? (
                <div className="text-slate-800 dark:text-slate-200">
                  <MessageMarkdown
                    text={textKhac}
                    onCitationClick={bamTrichKhac}
                    validSources={validKhac}
                  />
                  {khacDang && khacStatus && (
                    <div className="mt-1.5 flex items-center gap-2 text-[11px] italic text-slate-500 dark:text-slate-400">
                      <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-pulse" />
                      {khacStatus}
                    </div>
                  )}
                </div>
              ) : null}
              {moTaLoc(locKhac) && (
                <p className="text-[11px] text-slate-500 dark:text-slate-400 flex items-start gap-1.5">
                  <Lock className="w-3 h-3 shrink-0 mt-0.5" />
                  Không dựa trên {moTaLoc(locKhac)} — phạm vi dữ liệu không cho gửi ra ngoài máy chủ.
                </p>
              )}
              {khac?.trang_thai === 'xong' &&
                (khac.grounding_status === 'partial' || khac.grounding_status === 'uncited') && (
                  <p className="text-[11px] text-amber-700 dark:text-amber-300 flex items-start gap-1.5">
                    <AlertTriangle className="w-3 h-3 shrink-0 mt-0.5" />
                    Một phần câu trả lời này không đối chiếu được với nguồn.
                  </p>
                )}
              {!khacDang && nguonKhac.length > 0 && (
                <SourcePanel
                  sources={nguonKhac}
                  messageId={`${message.id}-khac`}
                  open={showNguonKhac}
                  onToggle={() => setShowNguonKhac((v) => !v)}
                  focusN={focusNguonKhac}
                  cited={citedKhac}
                  onPreview={onPreview}
                  onDownload={onDownload}
                />
              )}
              {khac?.trang_thai === 'xong' && (
                <div className="flex flex-wrap gap-x-2 text-[10px] text-slate-500 dark:text-slate-400">
                  <span>{khac.model}</span>
                  {khac.ms ? <span>· {fmtSec(khac.ms)}</span> : null}
                  {khac.cost_usd != null && <span>· {fmtUsd(khac.cost_usd)}</span>}
                  {khac.da_che ? <span>· đã che {khac.da_che} chỗ định danh</span> : null}
                </div>
              )}
            </>
          )}

          {khacLoi && (
            <div className="flex items-start gap-1.5 text-[11px] text-red-700 dark:text-red-300">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-px" />
              <span>{khacLoi}</span>
              {coKhac && (
                <button
                  type="button"
                  onClick={() => void chayKhac(true)}
                  className="underline font-semibold shrink-0"
                >
                  Thử lại
                </button>
              )}
            </div>
          )}
          <p className="text-[10px] italic text-slate-400 dark:text-slate-500">
            Ý kiến thứ hai từ model ngoài, chỉ để so sánh — không lưu vào lịch sử hỏi đáp của bot.
          </p>
        </div>
      )}
    </div>
  );
};
