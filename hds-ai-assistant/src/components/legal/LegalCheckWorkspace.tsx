import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import type {
  BoMau,
  ChatMessage,
  ConversationSummary,
  RaSoatKetQua,
  RaSoatLoai,
  TempAttachment,
  TemplateFile,
} from '../../types';
import { ATTACH_ACCEPT_FALLBACK } from '../../constants';
import { ChatMessageItem } from '../chat/ChatMessageItem';
import { BoMauPicker } from '../chat/BoMauPicker';
import {
  Scale,
  Paperclip,
  Send,
  Loader2,
  FileText,
  FilePlus2,
  Files,
  ListChecks,
  ChevronDown,
  ChevronUp,
  Search,
  X,
  AlertTriangle,
  Download,
  History,
  Square,
  Plus,
  Trash2,
  ShieldAlert,
} from 'lucide-react';

/** Rà soát rủi ro theo danh mục điều khoản chuẩn (kế hoạch ngày 7–8). */
const RA_SOAT_BADGE: Record<string, { label: string; cls: string }> = {
  dat: { label: 'ĐẠT', cls: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300' },
  canh_bao: { label: 'CẢNH BÁO', cls: 'bg-amber-100 text-amber-900 dark:bg-amber-950/50 dark:text-amber-300' },
  thieu: { label: 'THIẾU', cls: 'bg-red-100 text-red-800 dark:bg-red-950/50 dark:text-red-300' },
};
const RUI_RO_LABEL: Record<string, { label: string; cls: string }> = {
  thap: { label: 'Rủi ro thấp', cls: 'text-emerald-700 dark:text-emerald-300' },
  trung_binh: { label: 'Rủi ro trung bình', cls: 'text-amber-700 dark:text-amber-300' },
  cao: { label: 'Rủi ro cao', cls: 'text-red-700 dark:text-red-300' },
};

const RaSoatModal: React.FC<{
  attachments: TempAttachment[];
  onClose: () => void;
  showToast: (msg: string, kind?: 'success' | 'error' | 'info') => void;
}> = ({ attachments, onClose, showToast }) => {
  const usable = attachments.filter((a) => a.id != null);
  const [fileId, setFileId] = useState<number | null>(usable[0]?.id ?? null);
  const [loai, setLoai] = useState('');
  const [loaiList, setLoaiList] = useState<RaSoatLoai[]>([]);
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [ketQua, setKetQua] = useState<RaSoatKetQua | null>(null);

  useEffect(() => {
    api.getRaSoatLoai().then(setLoaiList).catch(() => setLoaiList([]));
  }, []);

  const run = async () => {
    if (fileId == null) return;
    setBusy(true);
    try {
      const att = usable.find((a) => a.id === fileId);
      const res = await api.raSoatHopDong({ temp_file_id: fileId, loai: loai || null, tieu_de: att?.filename });
      setKetQua(res);
    } catch (err: any) {
      showToast(err?.message || 'Không rà soát được.', 'error');
    } finally {
      setBusy(false);
    }
  };
  const exportDocx = async () => {
    if (!ketQua) return;
    setExporting(true);
    try {
      await api.exportRaSoat(ketQua, ketQua.tieu_de || 'hop-dong', `ra-soat-${(ketQua.tieu_de || 'hop-dong').replace(/\.[^.]+$/, '')}.docx`);
    } catch (err: any) {
      showToast(err?.message || 'Không xuất được báo cáo.', 'error');
    } finally {
      setExporting(false);
    }
  };

  const rr = ketQua ? RUI_RO_LABEL[ketQua.tong_ket?.muc_rui_ro] || RUI_RO_LABEL.thap : null;
  return (
    <div className="fixed inset-0 z-50 bg-slate-950/60 backdrop-blur-sm flex items-center justify-center p-4" onClick={onClose} role="presentation">
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-4xl max-h-[90vh] overflow-y-auto bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-2xl">
        <div className="p-5 border-b border-slate-200 dark:border-slate-800 flex items-start justify-between gap-3 sticky top-0 bg-white dark:bg-slate-900 rounded-t-2xl">
          <div>
            <h3 className="font-bold text-sm flex items-center gap-2"><ShieldAlert className="w-4 h-4 text-hds-gold" /> Rà soát rủi ro theo danh mục điều khoản</h3>
            <p className="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">
              Đối chiếu hợp đồng với danh mục điều khoản bắt buộc theo loại + ngưỡng bất thường theo luật (lãi suất, phạt, thử việc…). Mỗi mục: Đạt / Cảnh báo / Thiếu, giải thích, đề xuất sửa, căn cứ và đoạn luật trong kho.
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Đóng"><X className="w-5 h-5 text-slate-400" /></button>
        </div>
        <div className="p-5 space-y-4">
          <div className="flex flex-wrap gap-2 items-end">
            <label className="space-y-1 flex-1 min-w-[220px]">
              <span className="text-[11px] font-bold text-slate-700 dark:text-slate-300">Hợp đồng đính kèm</span>
              <select value={fileId ?? ''} onChange={(e) => setFileId(e.target.value ? Number(e.target.value) : null)} className="w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-700 dark:bg-slate-800 text-xs">
                {usable.length === 0 && <option value="">(chưa có file đính kèm đọc xong)</option>}
                {usable.map((a) => <option key={a.id ?? a.filename} value={a.id ?? ''}>{a.filename}</option>)}
              </select>
            </label>
            <label className="space-y-1 min-w-[200px]">
              <span className="text-[11px] font-bold text-slate-700 dark:text-slate-300">Loại hợp đồng</span>
              <select value={loai} onChange={(e) => setLoai(e.target.value)} className="w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-700 dark:bg-slate-800 text-xs">
                <option value="">Tự nhận diện</option>
                {loaiList.map((l) => <option key={l.ma} value={l.ma}>{l.ten}</option>)}
              </select>
            </label>
            <button type="button" onClick={run} disabled={busy || fileId == null} className="px-4 py-2 rounded-lg bg-hds-navy text-hds-gold text-xs font-bold flex items-center gap-1.5 disabled:opacity-50">
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <ListChecks className="w-4 h-4" />} Rà soát
            </button>
            {ketQua && (
              <button type="button" onClick={exportDocx} disabled={exporting} className="px-4 py-2 rounded-lg border border-slate-300 dark:border-slate-700 text-xs font-bold flex items-center gap-1.5 disabled:opacity-50">
                {exporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />} Xuất báo cáo Word
              </button>
            )}
          </div>

          {ketQua && (
            <>
              <div className="flex flex-wrap items-center gap-3 text-xs">
                <span>Loại: <strong>{ketQua.ten_loai}</strong> {ketQua.do_tin_cay ? `(${Math.round(ketQua.do_tin_cay * 100)}%)` : ''}</span>
                <span>· {ketQua.so_dieu_khoan} điều khoản</span>
                <span className={`font-bold ${rr?.cls}`}>· {rr?.label}</span>
                <span className="text-slate-500">· {ketQua.tong_ket.dat} đạt, {ketQua.tong_ket.canh_bao} cảnh báo, {ketQua.tong_ket.thieu} thiếu</span>
              </div>
              <div className="rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
                <table className="w-full text-xs">
                  <thead className="bg-slate-50 dark:bg-slate-800 text-[10px] uppercase text-slate-500">
                    <tr>
                      <th className="text-left px-3 py-2 w-8">#</th>
                      <th className="text-left px-3 py-2">Mục</th>
                      <th className="text-left px-3 py-2 w-24">Trạng thái</th>
                      <th className="text-left px-3 py-2">Giải thích · Đề xuất · Căn cứ</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ketQua.muc.map((m, i) => {
                      const b = RA_SOAT_BADGE[m.trang_thai] || RA_SOAT_BADGE.dat;
                      return (
                        <tr key={m.ma + i} className="border-t border-slate-100 dark:border-slate-800 align-top">
                          <td className="px-3 py-2 text-slate-400">{i + 1}</td>
                          <td className="px-3 py-2">
                            <span className="font-bold text-slate-800 dark:text-slate-100">{m.ten}</span>
                            {m.dieu_khoan && <span className="block text-[10px] text-slate-500">{m.dieu_khoan}</span>}
                            {m.trich && <span className="block mt-1 text-[10px] italic text-slate-500 border-l-2 border-slate-300 pl-2">{m.trich}</span>}
                          </td>
                          <td className="px-3 py-2"><span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${b.cls}`}>{b.label}</span></td>
                          <td className="px-3 py-2 text-slate-700 dark:text-slate-300 space-y-1">
                            {m.giai_thich && <p>{m.giai_thich}</p>}
                            {m.de_xuat && m.trang_thai !== 'dat' && <p><span className="font-semibold">Đề xuất:</span> {m.de_xuat}</p>}
                            {m.can_cu && <p className="text-[10px] text-slate-500">Căn cứ: {m.can_cu}</p>}
                            {m.can_cu_kho?.map((c, j) => (
                              <p key={j} className="text-[10px] text-slate-500 border-l-2 border-hds-gold pl-2">
                                <span className="font-semibold">{c.title}{c.so_hieu ? ` (${c.so_hieu})` : ''}:</span> {c.trich}
                              </p>
                            ))}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="text-[10px] text-slate-500">AI hỗ trợ rà soát theo danh mục; luật sư HDS rà soát và chịu trách nhiệm cuối cùng.</p>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

/**
 * Tab "Kiểm tra pháp lý & tạo file mẫu" — yêu cầu chủ dự án 26/08/2026.
 *
 * Khung chat RIÊNG (không đụng state hội thoại của tab Hội thoại AI):
 *   1. Tải hồ sơ khách gửi (.docx/.pdf/ảnh scan) lên làm file "dùng xong bỏ" —
 *      máy chủ tự trích văn bản + OCR, KHÔNG nạp vào kho tri thức.
 *   2. Hỏi ở chế độ legal_review: AI đối chiếu hồ sơ với luật / án lệ / bản án
 *      / quan điểm pháp lý đã học, kết luận từng điểm kèm [Nguồn n].
 *   3. Chọn một file trong kệ mẫu (menu ngay dưới khung chat) rồi bấm
 *      "Tạo file mẫu": AI thay thông tin chủ thể vào ĐÚNG file .docx gốc,
 *      giữ nguyên định dạng, trả bảng đối chiếu + nút tải về (nút nằm trong
 *      ChatMessageItem để mở lại từ lịch sử vẫn thấy).
 */

const nowLabel = () =>
  new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });


/**
 * Cache mức module: App.tsx render tab theo điều kiện nên chuyển tab là
 * component bị UNMOUNT — không có cache này, người dùng liếc sang tab khác một
 * giây là mất sạch hội thoại đang phân tích. Mọi thay đổi tin nhắn đi qua cache
 * TRƯỚC rồi mới vào React state (write-through), nhờ vậy các sự kiện stream đến
 * SAU khi unmount vẫn được giữ và hiện lại đầy đủ khi quay về tab.
 *
 * `userId` khoá cache theo người đăng nhập: đăng xuất rồi người khác đăng nhập
 * trên cùng trình duyệt KHÔNG được thấy hội thoại (hồ sơ khách!) của người
 * trước. F5 là về trạng thái trống; file tạm phía máy chủ tự hết hạn sau 6h.
 */
const sessionCache: {
  userId: number | string | null;
  messages: ChatMessage[];
  serverConvId: number | null;
  attachments: TempAttachment[];
  /** Đang có lượt stream chạy — sống qua unmount để quay lại tab không gửi
   *  chồng lượt thứ hai trong lúc lượt cũ (tạo bộ file dài) còn chạy. */
  busy: boolean;
  /** Bộ dội cache ra màn hình của BẢN ĐANG GẮN. Lượt stream chạy tiếp sau khi
   *  component unmount (api.chatStream không có AbortController), và các hàm
   *  applyMessages/rememberBusy nó nắm trong closure thuộc về bản ĐÃ CHẾT —
   *  gọi setState ở đó không vẽ ra gì. Không có con trỏ này thì rời tab giữa
   *  lúc AI đang trả lời rồi quay lại là câu trả lời đứng im mãi và busy kẹt ở
   *  true → ô nhập lẫn ba nút đều bị khoá, người dùng không gõ được gì nữa. */
  sync: (() => void) | null;
  /** Tăng mỗi lần đổi người đăng nhập. Lượt stream đang chạy giữ epoch lúc nó
   *  bắt đầu — epoch lệch là người khác đã đăng nhập, mọi sự kiện về sau của
   *  lượt cũ bị vứt, tuyệt đối không ghi hội thoại (hồ sơ khách!) của người
   *  trước vào màn hình người sau. */
  epoch: number;
  /** Tay cầm cắt lượt đang chạy. Ở ĐÂY chứ không phải useRef: chuyển tab là
   *  component bị tháo hẳn, ref rỗng lại — khi đó nút Dừng hiện ra mà bấm
   *  không ăn gì, ô nhập khoá cứng. */
  stopper: AbortController | null;
} = { userId: null, messages: [], serverConvId: null, attachments: [], busy: false,
      sync: null, epoch: 0, stopper: null };

export const LegalCheckWorkspace: React.FC = () => {
  const { showToast, currentUser } = useApp();

  // Người dùng đổi (đăng xuất/đăng nhập lại) → xoá sạch cache của người trước
  // TRƯỚC khi các useState bên dưới đọc nó làm giá trị khởi tạo.
  const uid = currentUser?.id ?? null;
  if (sessionCache.userId !== uid) {
    sessionCache.userId = uid;
    sessionCache.messages = [];
    sessionCache.serverConvId = null;
    sessionCache.attachments = [];
    sessionCache.busy = false;
    sessionCache.epoch += 1; // vô hiệu mọi lượt stream còn chạy của người trước
    sessionCache.stopper?.abort();   // và cắt hẳn nó, đừng để chạy cho không
    sessionCache.stopper = null;
  }

  const [messages, setMessages] = useState<ChatMessage[]>(sessionCache.messages);
  const [serverConvId, setServerConvId] = useState<number | null>(sessionCache.serverConvId);
  const [attachments, setAttachments] = useState<TempAttachment[]>(sessionCache.attachments);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(sessionCache.busy);
  const [uploading, setUploading] = useState(false);
  // Đuôi file lấy TỪ MÁY CHỦ (GET /upload/formats) — chép tay vào giao diện là
  // có ngày hộp thoại chặn đúng file mà máy chủ đọc được.
  const [acceptExts, setAcceptExts] = useState<string>(ATTACH_ACCEPT_FALLBACK);

  useEffect(() => {
    api
      .getUploadFormats()
      .then((res) => {
        const exts = (res?.extensions || []).filter((e) => typeof e === 'string');
        if (exts.length) setAcceptExts(exts.join(','));
      })
      .catch(() => {
        /* im lặng — đã có danh sách dự phòng, máy chủ vẫn là chốt cuối */
      });
  }, []);

  // Lịch sử PHIÊN kiểm tra (kind='legal' trên máy chủ): mở lại phiên cũ là
  // bot đọc lại toàn bộ diễn biến (tin nhắn nạp về + bộ nhớ dài phía backend)
  // và trả lời tiếp được. Phiên chỉ mất khi người dùng bấm xoá.
  const [sessions, setSessions] = useState<ConversationSummary[]>([]);
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const [sessionLoading, setSessionLoading] = useState(false);

  const [templates, setTemplates] = useState<TemplateFile[]>([]);
  const [templatesLoaded, setTemplatesLoaded] = useState(false);
  const [templateOpen, setTemplateOpen] = useState(false);
  const [templateSearch, setTemplateSearch] = useState('');
  const [selectedTemplate, setSelectedTemplate] = useState<TemplateFile | null>(null);
  // Bộ mẫu hồ sơ (15/09/2026): "Tạo bộ file" với bộ đang chọn = điền dữ liệu
  // (hồ sơ đính kèm + hội thoại) vào từng file .docx của bộ. Rỗng = cả bộ.
  const [selectedBoMau, setSelectedBoMau] = useState<BoMau | null>(null);
  const [boMauFileIds, setBoMauFileIds] = useState<number[]>([]);
  const [raSoatOpen, setRaSoatOpen] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // Hai cú "tạo hội thoại" chạy song song (upload trong lúc đang gửi câu đầu)
  // phải nhận về CÙNG một conversation — giữ promise, không giữ mỗi kết quả.
  const convPromiseRef = useRef<Promise<number> | null>(null);

  // ---- Write-through helpers: cache trước, MÀN HÌNH ĐANG GẮN sau --------
  // Mọi lối ghi đều đi qua sessionCache.sync?.() chứ KHÔNG gọi thẳng setState
  // của bản mình: sự kiện stream có thể đến khi bản này đã bị unmount, lúc đó
  // chỉ bản đang gắn mới vẽ được.
  const applyMessages = (fn: (prev: ChatMessage[]) => ChatMessage[]) => {
    sessionCache.messages = fn(sessionCache.messages);
    sessionCache.sync?.();
  };
  const updateMessage = (id: string, patch: (m: ChatMessage) => ChatMessage) => {
    applyMessages((prev) => prev.map((m) => (m.id === id ? patch(m) : m)));
  };
  const applyAttachments = (fn: (prev: TempAttachment[]) => TempAttachment[]) => {
    sessionCache.attachments = fn(sessionCache.attachments);
    sessionCache.sync?.();
  };
  const rememberConv = (id: number) => {
    sessionCache.serverConvId = id;
    sessionCache.sync?.();
  };
  const rememberBusy = (v: boolean) => {
    sessionCache.busy = v;
    sessionCache.sync?.();
  };

  useEffect(() => {
    // Đăng ký làm "màn hình đang gắn" và bắt kịp ngay mọi thứ đã xảy ra trong
    // lúc tab đóng; huỷ đăng ký khi rời tab để lượt stream còn chạy chỉ ghi
    // vào cache.
    sessionCache.sync = () => {
      setMessages(sessionCache.messages);
      setAttachments(sessionCache.attachments);
      setServerConvId(sessionCache.serverConvId);
      setBusy(sessionCache.busy);
    };
    sessionCache.sync();
    return () => {
      sessionCache.sync = null;
    };
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    // Nạp danh sách kệ mẫu một lần khi mở tab — menu chọn mẫu cần nó ngay.
    (async () => {
      try {
        const res = await api.listTemplateFiles();
        setTemplates(res.items || []);
      } catch {
        // Không có mẫu thì menu trống với lời hướng dẫn — không chặn chat.
      } finally {
        setTemplatesLoaded(true);
      }
    })();
  }, []);

  const handleTemplateDownload = async (t: TemplateFile) => {
    try {
      await api.downloadDocument(t.id, t.title);
    } catch (err: any) {
      showToast(err?.message || `Không tải được «${t.title}».`, 'error');
    }
  };

  const filteredTemplates = useMemo(() => {
    const q = templateSearch.trim().toLowerCase();
    if (!q) return templates;
    return templates.filter(
      (t) => t.title.toLowerCase().includes(q) || (t.folder || '').toLowerCase().includes(q)
    );
  }, [templates, templateSearch]);

  const ensureConversation = async (): Promise<number> => {
    if (sessionCache.serverConvId != null) return sessionCache.serverConvId;
    if (!convPromiseRef.current) {
      convPromiseRef.current = api
        .createConversation('legal')
        .then((res) => {
          rememberConv(res.conversation_id);
          return res.conversation_id;
        })
        .catch((err) => {
          convPromiseRef.current = null; // lần sau thử lại được
          throw err;
        });
    }
    return convPromiseRef.current;
  };

  const refreshSessions = async () => {
    try {
      setSessions(await api.listConversations(50, 'legal'));
    } catch {
      // Không tải được danh sách phiên thì thôi — không chặn tab.
    }
  };

  /** Tin nhắn máy chủ → ChatMessage của khung chat (cùng khuôn với tab Hội
   *  thoại AI: sources ưu tiên evidence để bảng nguồn hiện lại đầy đủ). */
  const mapServer = (rows: any[]): ChatMessage[] =>
    (rows || []).map((m) => ({
      id: `h-${m.id}`,
      sender: m.role === 'user' ? ('user' as const) : ('ai' as const),
      text: m.content,
      timestamp: /(\d{1,2}:\d{2})/.exec(m.created_at || '')?.[1] || '',
      serverMessageId: m.id,
      sources: m.evidence ?? m.sources,
      grounding_status: m.grounding_status,
      answer_mode: m.answer_mode,
    }));

  /** Mở lại một phiên cũ: nạp toàn bộ tin nhắn + các file đính kèm CÒN HẠN.
   *  Backend tự nối tiếp ngữ cảnh (lượt gần nhất nguyên văn + bản tóm tắt
   *  phần cũ) nên hỏi tiếp là bot hiểu ngay, không cần kể lại. */
  const openSession = async (id: number) => {
    // uploading: lượt tải file đang chạy sẽ gắn chip vào cache — đổi phiên
    // giữa chừng là chip của phiên cũ mọc vào phiên mới.
    if (busy || uploading || sessionLoading) return;
    setSessionLoading(true);
    try {
      const [hist, tf] = await Promise.all([
        api.getChatHistory(id),
        api.getConversationTempFiles(id).catch(() => ({ items: [] })),
      ]);
      sessionCache.messages = mapServer(hist.messages as any[]);
      sessionCache.serverConvId = id;
      sessionCache.attachments = (tf.items || []).map((f) => ({
        id: f.id,
        filename: f.filename,
        chunks: f.chunks,
        status: 'ok',
        warnings: [],
        textChars: 0,
      }));
      sessionCache.busy = false;
      convPromiseRef.current = Promise.resolve(id);
      sessionCache.sync?.();
      setSessionsOpen(false);
    } catch (err: any) {
      showToast(err?.message || 'Không mở lại được phiên này.', 'error');
    } finally {
      setSessionLoading(false);
    }
  };

  /** Phiên mới: chỉ dọn màn hình — hội thoại trên máy chủ được tạo khi người
   *  dùng gửi câu đầu hoặc đính kèm file (ensureConversation), tránh đẻ phiên
   *  rỗng mỗi lần bấm. */
  const newSession = () => {
    if (busy || uploading) return;
    sessionCache.messages = [];
    sessionCache.serverConvId = null;
    sessionCache.attachments = [];
    sessionCache.busy = false;
    convPromiseRef.current = null;
    sessionCache.sync?.();
    setSessionsOpen(false);
  };

  const deleteSession = async (id: number) => {
    // Đang stream mà xoá đúng phiên đang chạy là lượt trả lời rơi vào một
    // hội thoại đã chết — chờ xong rồi xoá.
    if (busy || uploading) return;
    if (!window.confirm('Xoá phiên này và toàn bộ nội dung của nó?')) return;
    try {
      await api.deleteConversation(id);
      setSessions((prev) => prev.filter((c) => c.id !== id));
      if (sessionCache.serverConvId === id) newSession();
    } catch (err: any) {
      showToast(err?.message || 'Không xoá được phiên.', 'error');
    }
  };

  const handleUpload = async (files: FileList | null) => {
    if (!files || !files.length || uploading) return;
    setUploading(true);
    try {
      const conv = await ensureConversation();
      for (const file of Array.from(files)) {
        try {
          const res = await api.uploadExtract({ conversation_id: conv, file });
          applyAttachments((prev) => [
            ...prev,
            {
              id: typeof res.temp_file_id === 'number' ? res.temp_file_id : null,
              filename: res.filename || file.name,
              chunks: res.chunks || 0,
              status: res.status || 'ok',
              warnings: Array.isArray(res.warnings) ? res.warnings : [],
              textChars: typeof res.text_chars === 'number' ? res.text_chars : 0,
            },
          ]);
          if (res.status === 'warning') {
            showToast(
              `«${file.name}» là bản scan/đọc có cảnh báo — nội dung có thể thiếu hoặc sai ký tự.`,
              'info'
            );
          }
        } catch (err: any) {
          showToast(err?.message || `Không đọc được «${file.name}».`, 'error');
        }
      }
    } catch (err: any) {
      showToast(err?.message || 'Không tạo được hội thoại để đính kèm file.', 'error');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const removeAttachment = async (idx: number) => {
    const target = attachments[idx];
    if (!target) return;
    // Gỡ THẬT trên máy chủ — không thì bot vẫn đọc file "đã gỡ" ở lượt sau.
    if (target.id != null) {
      try {
        await api.deleteTempFile(target.id);
      } catch (err: any) {
        showToast(err?.message || `Không gỡ được «${target.filename}» trên máy chủ.`, 'error');
        return; // giữ chip để người dùng biết file vẫn còn
      }
    }
    // Lọc theo CHÍNH đối tượng đó, không theo chỉ số: giữa lúc chờ máy chủ xoá
    // xong, một lượt tải lên khác có thể đã chèn thêm chip và làm lệch chỉ số —
    // gỡ nhầm chip là người dùng tưởng hồ sơ còn đính kèm trong khi đã mất.
    applyAttachments((prev) => prev.filter((a) => a !== target));
  };

  /** Gửi một lượt hỏi qua /chat/stream — dùng chung cho cả ba nút. */
  const send = async (
    question: string,
    templateDocId?: number,
    makeFiles?: boolean,
    checkTemplate?: boolean,
  ) => {
    if (sessionCache.busy || uploading) return;
    // Lượt này thuộc về người đang đăng nhập BÂY GIỜ: đổi người giữa chừng là
    // epoch lệch và mọi sự kiện còn lại của lượt bị vứt (xem sessionCache).
    const epoch = sessionCache.epoch;
    const alive = () => sessionCache.epoch === epoch;
    const stopper = new AbortController();
    sessionCache.stopper = stopper;
    rememberBusy(true);
    setInput('');

    applyMessages((prev) => [
      ...prev,
      {
        id: `u-${Date.now()}`,
        sender: 'user',
        text: question,
        timestamp: nowLabel(),
        used_temp_files: attachments.length
          ? attachments.map((a) => a.filename)
          : undefined,
      },
    ]);

    const aiMsgId = `ai-${Date.now()}`;
    let opened = false;
    try {
      const conv = await ensureConversation();
      await api.chatStream(
        {
          question,
          conversation_id: conv,
          use_temp: attachments.length > 0,
          // Điền mẫu / tạo bộ file là luồng trả lời trực tiếp; các câu hỏi
          // thường đi chế độ rà soát pháp lý (prompt riêng + ưu tiên kệ luật).
          // Đối chiếu với mẫu: mode riêng + mẫu đã chọn, KHÔNG đi luồng điền mẫu.
          mode: checkTemplate
            ? 'template_check'
            : templateDocId || makeFiles
              ? undefined
              : 'legal_review',
          template_doc_id: templateDocId ?? undefined,
          make_files: makeFiles || undefined,
          // Bộ mẫu đang chọn: máy chủ chỉ dùng khi lượt là lệnh tạo file.
          bo_mau_id: selectedBoMau?.id ?? undefined,
          bo_mau_file_ids:
            selectedBoMau && boMauFileIds.length > 0 ? boMauFileIds : undefined,
          signal: stopper.signal,
        },
        (evt) => {
          if (!alive()) return;
          if (evt.type === 'start') {
            if (evt.conversation_id) rememberConv(evt.conversation_id);
            applyMessages((prev) => [
              ...prev,
              {
                id: aiMsgId,
                sender: 'ai',
                text: '',
                timestamp: nowLabel(),
                isStreaming: true,
                statusLabel: 'Đang chuẩn bị…',
              },
            ]);
            opened = true;
            return;
          }
          if (evt.type === 'status' && evt.label) {
            const label = evt.label;
            updateMessage(aiMsgId, (m) => ({ ...m, statusLabel: label }));
            return;
          }
          if (evt.type === 'meta') {
            updateMessage(aiMsgId, (m) => ({
              ...m,
              sources: evt.sources,
              grounding_status: evt.grounding_status,
              answer_mode: evt.answer_mode,
            }));
            return;
          }
          if (evt.type === 'delta' && evt.text) {
            const piece = evt.text;
            updateMessage(aiMsgId, (m) => ({ ...m, text: m.text + piece, statusLabel: undefined }));
            return;
          }
          if (evt.type === 'replace') {
            updateMessage(aiMsgId, (m) => ({
              ...m,
              text: evt.text ?? m.text,
              statusLabel: undefined,
              grounding_status: evt.grounding_status ?? m.grounding_status,
              answer_mode: evt.answer_mode ?? m.answer_mode,
            }));
            return;
          }
          if (evt.type === 'done') {
            updateMessage(aiMsgId, (m) => ({
              ...m,
              isStreaming: false,
              statusLabel: undefined,
              latency_ms: evt.latency_ms,
              serverMessageId: evt.message_id,
              timings: evt.timings,
              grounding_status: evt.grounding_status ?? m.grounding_status,
              answer_mode: evt.answer_mode ?? m.answer_mode,
              sources: evt.sources ?? m.sources,
            }));
          }
        }
      );
    } catch (err: any) {
      if (!alive()) return;
      // Bam "Dung" khong phai su co: giu phan chu da viet, dong con tro nhap
      // nhay, khong bao do. May chu da luu dung phan nay kem dau bi cat.
      if (err?.code === api.DUNG_BOI_NGUOI_DUNG) {
        updateMessage(aiMsgId, (m) => ({
          ...m,
          isStreaming: false,
          statusLabel: undefined,
          text: m.text
            ? `${m.text}

_(Người dùng đã dừng câu trả lời giữa chừng.)_`
            : 'Đã dừng trước khi AI kịp viết câu nào.',
        }));
        return;
      }
      const errMsg = err?.message || 'Có lỗi xảy ra khi hỏi AI.';
      if (opened) {
        updateMessage(aiMsgId, (m) => ({
          ...m,
          isStreaming: false,
          statusLabel: undefined,
          text: m.text
            ? `${m.text}\n\n_(Câu trả lời bị ngắt giữa chừng: ${errMsg})_`
            : errMsg,
          isError: !m.text,
        }));
      } else {
        applyMessages((prev) => [
          ...prev,
          { id: `err-${Date.now()}`, sender: 'ai', text: errMsg, timestamp: nowLabel(), isError: true },
        ]);
      }
    } finally {
      if (sessionCache.stopper === stopper) sessionCache.stopper = null;
      if (alive()) {
        rememberBusy(false);
        textareaRef.current?.focus();
      }
    }
  };

  /** Cat luot tra loi dang chay. Dong ket noi la tin hieu de may chu bat co
   *  huy va model ngung sinh chu — khong phai chi giau chu di. */
  const handleStop = () => {
    if (sessionCache.stopper) {
      sessionCache.stopper.abort();
      return;
    }
    // Không còn tay cầm mà cờ vẫn bật: lượt cũ đã chết mà quên tắt cờ. Mở
    // khoá — nút Dừng KHÔNG BAO GIỜ được phép bấm mà không có gì xảy ra.
    rememberBusy(false);
  };

  const handleAsk = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const q = input.trim();
    if (!q || busy || uploading) return;
    void send(q);
  };

  const handleFillTemplate = () => {
    if (busy || uploading || !selectedTemplate) return;
    const extra = input.trim();
    const q = extra
      ? `Tạo file từ mẫu «${selectedTemplate.title}». ${extra}`
      : `Tạo file từ mẫu «${selectedTemplate.title}», thay thông tin chủ thể theo hồ sơ đính kèm và yêu cầu trong hội thoại.`;
    setTemplateOpen(false);
    void send(q, selectedTemplate.id);
  };

  const handleMakeFiles = () => {
    if (busy || uploading) return;
    const extra = input.trim();
    // Cần ít nhất một nguồn dữ liệu: câu lệnh hoặc hồ sơ đính kèm.
    if (!extra && attachments.length === 0 && !selectedBoMau) {
      showToast('Đính kèm hồ sơ, chọn bộ mẫu, hoặc mô tả cần tạo những file gì đã nhé.', 'info');
      return;
    }
    const q =
      extra ||
      (selectedBoMau
        ? `Điền thông tin khách (từ hồ sơ đính kèm và những gì đã trao đổi) vào bộ mẫu «${selectedBoMau.ten}», mỗi file mẫu một file, giữ nguyên điều khoản.`
        : 'Từ hồ sơ đính kèm, hãy lên danh sách và tạo các văn bản cần thiết (biên bản nghiệm thu, giấy đề nghị thanh toán các đợt…).');
    setTemplateOpen(false);
    void send(q, selectedTemplate?.id, true);
  };

  // Nhi (29/08/2026): "kiểm tra biểu mẫu của nhân viên khi up lên có đúng mẫu
  // quy định của công ty không". Cần cả file đính kèm lẫn mẫu đã chọn.
  const handleCheckTemplate = () => {
    if (busy || uploading || !selectedTemplate) return;
    if (attachments.length === 0) {
      showToast('Đính kèm file của nhân viên trước, rồi bấm Đối chiếu với mẫu.', 'info');
      return;
    }
    const extra = input.trim();
    const q = extra
      ? `Đối chiếu file đính kèm với mẫu «${selectedTemplate.title}». ${extra}`
      : `Đối chiếu file đính kèm với mẫu «${selectedTemplate.title}»: mục nào thiếu, mục nào khác mẫu, lỗi thể thức, và cần sửa gì.`;
    setTemplateOpen(false);
    void send(q, selectedTemplate.id, false, true);
  };

  return (
    <div className="flex-1 flex flex-col min-h-0 mx-auto w-full max-w-[1000px] px-3 sm:px-4">
      {/* Đầu trang */}
      <div className="py-3 border-b border-slate-200 dark:border-slate-800 flex items-center gap-3">
        <div className="w-9 h-9 rounded-xl bg-hds-navy flex items-center justify-center shrink-0">
          <Scale className="w-5 h-5 text-hds-gold" />
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-bold text-hds-navy dark:text-blue-200">
            Kiểm tra pháp lý &amp; tạo file mẫu
          </h2>
          <p className="text-[11px] text-slate-500 dark:text-slate-400 truncate">
            Tải hồ sơ khách gửi lên để AI đối chiếu luật, án lệ, bản án đã học — rồi tạo file từ mẫu chuẩn của HDS.
          </p>
        </div>
        {/* Phiên: mô hình nhiều hội thoại như tab Hội thoại AI. Mở lại phiên
            cũ là bot đọc lại toàn bộ diễn biến và trả lời tiếp. */}
        <div className="relative shrink-0 flex items-center gap-1.5">
          <button
            type="button"
            onClick={newSession}
            disabled={busy}
            className="flex items-center gap-1 px-2.5 py-1.5 text-[11px] font-bold rounded-lg bg-hds-navy hover:bg-hds-navy-light text-white transition-colors disabled:opacity-50"
            title="Bắt đầu phiên kiểm tra mới (phiên đang mở vẫn còn trong Phiên trước)"
          >
            <Plus className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Phiên mới</span>
          </button>
          <button
            type="button"
            onClick={() => {
              const next = !sessionsOpen;
              setSessionsOpen(next);
              if (next) void refreshSessions();
            }}
            className="flex items-center gap-1 px-2.5 py-1.5 text-[11px] font-bold rounded-lg bg-hds-soft dark:bg-slate-800 text-hds-navy dark:text-blue-300 hover:bg-blue-100 dark:hover:bg-slate-700 border border-blue-200 dark:border-slate-700 transition-colors"
            title="Mở lại một phiên kiểm tra trước đây"
          >
            <History className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Phiên trước</span>
            {sessionsOpen ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>
          {sessionsOpen && (
            <div className="absolute right-0 top-full mt-1.5 w-80 max-w-[85vw] bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl shadow-lg z-20 overflow-hidden">
              <div className="max-h-72 overflow-y-auto p-1.5">
                {sessionLoading && (
                  <p className="flex items-center gap-2 text-[11px] text-slate-500 dark:text-slate-400 px-2.5 py-2">
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    Đang nạp lại phiên…
                  </p>
                )}
                {sessions.length === 0 && !sessionLoading && (
                  <p className="text-[11px] text-slate-500 dark:text-slate-400 px-2.5 py-3 text-center">
                    Chưa có phiên nào. Phiên hiện ra ở đây sau khi bạn gửi câu hỏi
                    hoặc đính kèm hồ sơ đầu tiên.
                  </p>
                )}
                <ul className="space-y-0.5">
                  {sessions.map((c) => (
                    <li key={c.id} className="flex items-stretch gap-1">
                      <button
                        type="button"
                        onClick={() => void openSession(c.id)}
                        disabled={busy || sessionLoading}
                        className={`flex-1 min-w-0 text-left px-2.5 py-2 rounded-lg text-xs transition-colors disabled:opacity-50 ${
                          serverConvId === c.id
                            ? 'bg-hds-navy text-white'
                            : 'hover:bg-hds-soft dark:hover:bg-slate-800 text-slate-700 dark:text-slate-200'
                        }`}
                      >
                        <span className="font-semibold block truncate">{c.title}</span>
                        <span className="block text-[10px] opacity-70">
                          {/* Máy chủ trả timestamptz đầy đủ (micro giây + múi
                              giờ) — cắt còn 'YYYY-MM-DD HH:MM' cho đọc được. */}
                          {c.message_count} tin nhắn · {(c.updated_at || '').slice(0, 16)}
                        </span>
                      </button>
                      <button
                        type="button"
                        onClick={() => void deleteSession(c.id)}
                        disabled={busy || uploading}
                        className="shrink-0 self-center p-1.5 rounded-lg text-slate-400 hover:text-hds-red hover:bg-red-50 dark:hover:bg-red-950/40 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                        aria-label={`Xoá phiên ${c.title}`}
                        title="Xoá phiên này (không khôi phục được)"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Danh sách tin nhắn */}
      <div className="flex-1 overflow-y-auto py-4 no-scrollbar">
        {messages.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center text-center gap-3 text-slate-500 dark:text-slate-400">
            <Scale className="w-10 h-10 text-hds-gold" />
            <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">
              Bắt đầu bằng cách tải hồ sơ lên hoặc đặt câu hỏi
            </p>
            <ul className="text-xs space-y-1 max-w-md">
              <li>1. Bấm kẹp giấy để đính kèm hồ sơ khách gửi (.docx, .pdf, ảnh scan).</li>
              <li>2. Yêu cầu phân tích: "Hợp đồng này có điểm nào trái quy định không?"</li>
              <li>3. Chọn mẫu ở nút "Chọn file mẫu" rồi bấm "Tạo file mẫu" — AI thay chủ thể vào đúng file gốc.</li>
              <li>4. Hoặc bấm "Tạo bộ file" — AI tự lên danh sách văn bản (nghiệm thu, đề nghị thanh toán các đợt…) và soạn từng file từ hồ sơ.</li>
              <li>5. Chọn "Bộ mẫu" (nhóm .docx tải lên ở Quản trị → Bộ mẫu hồ sơ) rồi "Điền bộ này" — AI điền thông tin khách vào từng file của bộ.</li>
            </ul>
            <p className="text-[11px] italic">
              File đính kèm chỉ dùng trong hội thoại này, tự xoá sau 6 giờ, không vào kho tri thức.
            </p>
          </div>
        )}
        {messages.map((m) => (
          <ChatMessageItem key={m.id} message={m} />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* File đính kèm */}
      {attachments.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pb-2">
          {attachments.map((a, idx) => (
            <span
              key={`${a.filename}-${idx}`}
              className="inline-flex items-center gap-1.5 bg-blue-50 dark:bg-blue-950/50 border border-blue-200 dark:border-blue-900 text-blue-900 dark:text-blue-200 text-[11px] font-medium px-2 py-1 rounded-lg max-w-full"
            >
              <FileText className="w-3 h-3 shrink-0" />
              <span className="truncate">{a.filename}</span>
              {a.status === 'warning' && (
                <AlertTriangle className="w-3 h-3 text-amber-500 shrink-0" aria-label="Bản scan — đọc có cảnh báo" />
              )}
              {a.textChars > 0 && (
                <span className="text-blue-500/80 dark:text-blue-300/70 tabular-nums shrink-0">
                  {a.textChars.toLocaleString('vi-VN')} ký tự
                </span>
              )}
              <button
                type="button"
                onClick={() => void removeAttachment(idx)}
                className="hover:text-red-600"
                aria-label={`Bỏ ${a.filename}`}
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Máy chủ đã nói rõ đọc file gặp vấn đề gì — hiện nguyên văn, đừng nuốt.
          Người dùng đọc xong mới biết nên tin kết luận của AI tới đâu. */}
      {attachments.some((a) => a.warnings.length > 0) && (
        <div className="mb-2 rounded-xl border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 p-2.5 space-y-1.5">
          {attachments
            .filter((a) => a.warnings.length > 0)
            .map((a, idx) => (
              <div key={`w-${a.filename}-${idx}`} className="flex items-start gap-2">
                <AlertTriangle className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400 shrink-0 mt-px" />
                <p className="text-[11px] leading-relaxed text-amber-900 dark:text-amber-200">
                  <b className="break-all">{a.filename}</b>: {a.warnings.join(' · ')}
                </p>
              </div>
            ))}
          <p className="text-[10px] text-amber-800/80 dark:text-amber-300/70 pl-5.5">
            Nội dung đọc ra có thể thiếu hoặc sai ký tự — đối chiếu bản gốc trước khi dùng kết
            luận của AI.
          </p>
        </div>
      )}

      {/* Ô nhập + nút */}
      <form onSubmit={handleAsk} className="pb-2">
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-sm p-2 flex items-end gap-2">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading || busy}
            className="p-2 rounded-lg text-slate-500 hover:text-hds-navy hover:bg-hds-soft dark:hover:bg-slate-800 disabled:opacity-50 transition-colors shrink-0"
            title="Đính kèm hồ sơ (.docx, .pdf, ảnh scan…) — dùng xong bỏ, không vào kho"
          >
            {uploading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Paperclip className="w-5 h-5" />}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={acceptExts}
            className="hidden"
            onChange={(e) => void handleUpload(e.target.files)}
          />
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleAsk();
              }
            }}
            rows={2}
            placeholder="Mô tả yêu cầu: kiểm tra điểm nào, hoặc thông tin chủ thể cần điền vào mẫu…"
            className="flex-1 resize-none bg-transparent text-sm leading-relaxed focus:outline-none placeholder:text-slate-400 dark:text-slate-100 max-h-40"
            disabled={busy}
          />
          {/* Đang chạy thì đây là nút DỪNG. Quan trọng nhất ở tab này: lượt
              "Tạo bộ file" có thể chạy vài phút, không có lối thoát thì người
              dùng chỉ còn cách ngồi chờ hoặc tải lại trang. */}
          {busy ? (
            <button
              type="button"
              onClick={handleStop}
              className="p-2.5 rounded-xl bg-hds-red text-white hover:bg-red-700 transition-colors shrink-0"
              title="Dừng lượt đang chạy"
              aria-label="Dừng lượt đang chạy"
            >
              <Square className="w-5 h-5 fill-current" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={uploading || !input.trim()}
              className="p-2.5 rounded-xl bg-hds-navy text-hds-gold hover:bg-hds-navy-light disabled:opacity-50 transition-colors shrink-0"
              title={uploading ? 'Đang đọc file đính kèm — chờ một chút' : 'Phân tích pháp lý (Enter)'}
            >
              <Send className="w-5 h-5" />
            </button>
          )}
        </div>

        {/* Menu chọn file mẫu — ngay dưới khung chat theo yêu cầu */}
        <div className="mt-2 relative">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setTemplateOpen((v) => !v)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-xs font-semibold text-slate-700 dark:text-slate-200 hover:border-hds-gold transition-colors"
              aria-expanded={templateOpen}
            >
              <FilePlus2 className="w-3.5 h-3.5 text-hds-gold" />
              {selectedTemplate ? (
                <span className="max-w-[260px] truncate">{selectedTemplate.title}</span>
              ) : (
                'Chọn file mẫu'
              )}
              {templateOpen ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            </button>
            <button
              type="button"
              onClick={handleFillTemplate}
              disabled={busy || uploading || !selectedTemplate || !selectedTemplate.fillable}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-hds-gold text-hds-navy text-xs font-bold hover:bg-hds-gold-light disabled:opacity-50 transition-colors"
              title={
                selectedTemplate && !selectedTemplate.fillable
                  ? 'Mẫu này không phải .docx nên chưa điền tự động được'
                  : 'AI thay thông tin chủ thể vào đúng file mẫu gốc'
              }
            >
              <FilePlus2 className="w-3.5 h-3.5" />
              Tạo file mẫu
            </button>
            <button
              type="button"
              onClick={handleMakeFiles}
              disabled={busy || uploading}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-hds-navy text-hds-gold text-xs font-bold hover:bg-hds-navy-light disabled:opacity-50 transition-colors"
              title="AI đọc hồ sơ đính kèm, tự lên danh sách văn bản (nghiệm thu, đề nghị thanh toán các đợt…) rồi tạo từng file — khuôn lấy từ mẫu đã chọn hoặc file .docx đã tải lên"
            >
              <Files className="w-3.5 h-3.5" />
              Tạo bộ file
            </button>
            <button
              type="button"
              onClick={handleCheckTemplate}
              disabled={busy || uploading || !selectedTemplate}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-hds-navy dark:border-blue-400 text-hds-navy dark:text-blue-300 text-xs font-bold hover:bg-hds-soft dark:hover:bg-slate-800 disabled:opacity-50 transition-colors"
              title="AI so file nhân viên đính kèm với mẫu đã chọn: mục nào thiếu, mục nào khác mẫu, lỗi thể thức"
            >
              <ListChecks className="w-3.5 h-3.5" />
              Đối chiếu với mẫu
            </button>
            <button
              type="button"
              onClick={() => {
                if (!attachments.some((a) => a.id != null)) {
                  showToast('Đính kèm hợp đồng (.docx/.pdf) trước, đợi đọc xong rồi bấm Rà soát rủi ro.', 'info');
                  return;
                }
                setRaSoatOpen(true);
              }}
              disabled={busy || uploading}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-amber-500 text-amber-800 dark:text-amber-300 text-xs font-bold hover:bg-amber-50 dark:hover:bg-amber-950/40 disabled:opacity-50 transition-colors"
              title="Đối chiếu hợp đồng đính kèm với danh mục điều khoản bắt buộc theo loại + ngưỡng bất thường theo luật; xuất báo cáo Word"
            >
              <ShieldAlert className="w-3.5 h-3.5" />
              Rà soát rủi ro
            </button>
            {selectedTemplate && (
              <button
                type="button"
                onClick={() => setSelectedTemplate(null)}
                className="text-[11px] text-slate-500 hover:text-red-600"
              >
                Bỏ chọn
              </button>
            )}
            <BoMauPicker
              selected={selectedBoMau}
              selectedFileIds={boMauFileIds}
              onSelect={setSelectedBoMau}
              onFileIdsChange={setBoMauFileIds}
              onFillNow={handleMakeFiles}
              disabled={busy || uploading}
              direction="up"
            />
            <span className="text-[10px] text-slate-400 dark:text-slate-500 ml-auto hidden sm:inline">
              Mẹo: đặt {'{{ten_ben_a}}'} trong file mẫu để điền chính xác tuyệt đối.
            </span>
          </div>

          {templateOpen && (
            <div className="absolute bottom-full mb-2 left-0 w-full sm:w-[480px] max-h-72 overflow-y-auto bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl shadow-lg z-30 p-2 animate-fade-in">
              <div className="flex items-center gap-2 px-2 py-1.5 mb-1 bg-hds-soft dark:bg-slate-800 rounded-lg">
                <Search className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                <input
                  value={templateSearch}
                  onChange={(e) => setTemplateSearch(e.target.value)}
                  onKeyDown={(e) => {
                    // Enter ở ô tìm mẫu KHÔNG được submit form chat bên ngoài
                    // (lọc đã chạy realtime qua onChange rồi).
                    if (e.key === 'Enter') e.preventDefault();
                  }}
                  placeholder="Tìm theo tên mẫu hoặc thư mục…"
                  className="flex-1 bg-transparent text-xs focus:outline-none dark:text-slate-100"
                />
              </div>
              {!templatesLoaded ? (
                <div className="flex items-center gap-2 p-3 text-xs text-slate-500">
                  <Loader2 className="w-4 h-4 animate-spin" /> Đang nạp kệ mẫu…
                </div>
              ) : filteredTemplates.length === 0 ? (
                <p className="p-3 text-xs text-slate-500">
                  Kho chưa có file mẫu nào khớp. Đưa file .docx vào thư mục{' '}
                  <b>HỢP ĐỒNG MẪU</b> hoặc <b>THƯ MẪU - BIỂU MẪU</b> trong kho tài liệu (ổ mạng),
                  chờ quét (≤15 phút) rồi duyệt ở <b>Quản trị → Duyệt nhãn tài liệu</b>.
                </p>
              ) : (
                <ul className="space-y-0.5">
                  {filteredTemplates.map((t) => (
                    <li key={t.id} className="flex items-stretch gap-1">
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedTemplate(t);
                          setTemplateOpen(false);
                        }}
                        className={`flex-1 min-w-0 text-left px-2.5 py-2 rounded-lg text-xs transition-colors ${
                          selectedTemplate?.id === t.id
                            ? 'bg-hds-navy text-white'
                            : 'hover:bg-hds-soft dark:hover:bg-slate-800 text-slate-700 dark:text-slate-200'
                        }`}
                      >
                        <span className="font-semibold block truncate">{t.title}</span>
                        <span className="flex items-center gap-2 text-[10px] opacity-70">
                          <span>{t.doc_type === 'mau_hd' ? 'Hợp đồng mẫu' : 'Thư mẫu - biểu mẫu'}</span>
                          {t.folder && <span>· {t.folder}</span>}
                          {!t.fillable && <span className="text-amber-500">· không phải .docx — chỉ tải về</span>}
                        </span>
                      </button>
                      {/* Mẫu không phải .docx thì AI không điền được, nhưng nói
                          "chỉ tải về" mà không có chỗ bấm thì người dùng mắc kẹt
                          ngay tại đây. */}
                      {!t.fillable && (
                        <button
                          type="button"
                          onClick={() => void handleTemplateDownload(t)}
                          className="shrink-0 self-center px-2 py-1.5 rounded-lg text-[10px] font-bold text-hds-navy dark:text-blue-300 bg-hds-soft dark:bg-slate-800 hover:bg-blue-100 dark:hover:bg-slate-700 border border-blue-200 dark:border-slate-700 inline-flex items-center gap-1 transition-colors"
                          title={`Tải bản gốc «${t.title}» về máy`}
                        >
                          <Download className="w-3 h-3" />
                          <span>Tải về</span>
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </form>
      {raSoatOpen && (
        <RaSoatModal attachments={attachments} onClose={() => setRaSoatOpen(false)} showToast={showToast} />
      )}
    </div>
  );
};
