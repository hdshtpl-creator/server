import React, { useState } from 'react';
import { MessageMarkdown, CITE_RE } from './MessageMarkdown';
import { SourcePanel } from './SourcePanel';
import type { ChatMessage, ChatTimings } from '../../types';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import {
  User,
  Bot,
  FileText,
  Sliders,
  Clock,
  AlertTriangle,
  ThumbsUp,
  ThumbsDown,
  Send,
  CheckCircle2,
  Flag,
  StickyNote,
  Undo2,
  Download,
} from 'lucide-react';

const fmtSec = (ms: number) => (ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`);

/**
 * Bảng "thời gian đi vào đâu" cho một câu trả lời.
 *
 * Giúp trả lời đúng câu hỏi hay gặp nhất: vì sao câu đơn giản vẫn chậm. Thủ
 * phạm gần như luôn là ĐỌC PROMPT — phần này tỉ lệ thuận với lượng tài liệu
 * nhồi vào mỗi lượt, chứ không phụ thuộc câu hỏi khó hay dễ, cũng không phụ
 * thuộc kho tài liệu to hay nhỏ. Kho lớn vẫn ảnh hưởng thời gian/chỉ mục tra
 * cứu, nên backend tách riêng bước embedding và truy vấn vector để nhìn rõ.
 */
const TimingPanel: React.FC<{ t: ChatTimings }> = ({ t }) => {
  const rows: Array<[string, number | undefined, string]> = [
    ['Đọc cấu hình', t.cai_dat_ms, 'Đọc cấu hình AI hiện hành'],
    ['Đọc lịch sử', t.lich_su_ms, 'Lấy lượt trước và chủ đề hội thoại'],
    ['Dữ liệu xác định', t.du_lieu_cau_truc_ms, 'Router và truy vấn đếm/danh sách trực tiếp'],
    ['Tạo vector câu hỏi', t.embed_ms, 'Embedding bằng bge-m3'],
    ['Nạp model embedding', t.embed_load_ms, 'Nạp bge-m3 nếu đã hết keep-alive'],
    ['Tìm hybrid trong DB', t.vector_db_ms, 'Vector + từ khóa + xếp hạng lại'],
    ...((typeof t.embed_ms !== 'number' && typeof t.vector_db_ms !== 'number')
      ? [['Tra cứu tài liệu', t.tim_kiem_ms, 'Tìm đoạn liên quan trong kho'] as [string, number | undefined, string]]
      : []),
    ['Dữ liệu công ty', t.du_lieu_cong_ty_ms, 'Đọc khách hàng, vụ việc, nhân sự'],
    ['Chọn model', t.chon_model_ms, 'Kiểm tra model tự động/đang nóng'],
    ['Nạp model', t.load_ms, 'Đưa model từ ổ cứng vào bộ nhớ — >0 nghĩa là model đã bị đẩy ra'],
    ['AI đọc câu hỏi + tài liệu', t.prefill_ms, 'Tỉ lệ thuận với độ dài ngữ cảnh'],
    ['AI viết câu trả lời', t.gen_ms, 'Tỉ lệ thuận với độ dài câu trả lời'],
    ['Tổng end-to-end', t.tong_ms, 'Từ lúc backend bắt đầu chuẩn bị đến khi lưu xong câu trả lời'],
  ];
  const speed = (tok?: number, ms?: number) =>
    tok && ms ? `${Math.round(tok / (ms / 1000))} token/giây` : '—';

  return (
    <div className="text-[11px] bg-slate-50 dark:bg-slate-800/70 border border-slate-200 dark:border-slate-700 rounded-xl p-3 space-y-1.5">
      <div className="font-semibold text-slate-700 dark:text-slate-200">Thời gian đi vào đâu</div>
      {rows.map(([label, ms, hint]) =>
        typeof ms === 'number' ? (
          <div key={label} className="flex items-baseline justify-between gap-3" title={hint}>
            <span className="text-slate-500 dark:text-slate-400 truncate">{label}</span>
            <span className="font-mono text-slate-700 dark:text-slate-200 shrink-0">
              {fmtSec(ms)}
            </span>
          </div>
        ) : null
      )}
      <div className="pt-1.5 border-t border-slate-200 dark:border-slate-700 text-slate-500 dark:text-slate-400 space-y-0.5">
        {t.model && <div>Model: {t.model}</div>}
        {typeof t.prompt_tokens === 'number' && (
          <div>
            Ngữ cảnh: {t.prompt_tokens.toLocaleString('vi-VN')} token
            {typeof t.num_ctx === 'number' && ` / trần ${t.num_ctx.toLocaleString('vi-VN')}`}
            {typeof t.so_doan === 'number' && ` · ${t.so_doan} đoạn tài liệu`}
            {` · đọc ${speed(t.prompt_tokens, t.prefill_ms)}`}
          </div>
        )}
        {typeof t.gen_tokens === 'number' && (
          <div>
            Trả lời: {t.gen_tokens.toLocaleString('vi-VN')} token · viết{' '}
            {speed(t.gen_tokens, t.gen_ms)}
          </div>
        )}
        {typeof t.prompt_tokens === 'number' &&
          typeof t.num_ctx === 'number' &&
          t.prompt_tokens >= t.num_ctx - 32 && (
            <div className="text-amber-700 dark:text-amber-400 font-semibold">
              Ngữ cảnh đã chạm trần — phần đầu prompt bị cắt. Hãy giảm "Trần ký tự tài liệu"
              trong Cài đặt AI.
            </div>
          )}
      </div>
    </div>
  );
};

interface ChatMessageItemProps {
  message: ChatMessage;
}

export const ChatMessageItem: React.FC<ChatMessageItemProps> = ({ message }) => {
  const { showToast, saveNote, removeNote } = useApp();
  const isUser = message.sender === 'user';
  const isError = Boolean(message.isError);
  const usedFiles = message.used_temp_files ?? [];
  // Nguồn trích dẫn THU GỌN mặc định — người dùng bung ra khi cần kiểm chứng,
  // để câu trả lời gọn gàng chứ không bị danh sách nguồn đẩy dài màn hình.
  const [showSources, setShowSources] = useState(false);
  const [showTiming, setShowTiming] = useState(false);
  // Nguồn đang được soi (bấm chip số trong câu trả lời) — sáng viền vài giây
  // để mắt bắt được đúng nguồn giữa danh sách.
  const [focusSource, setFocusSource] = useState<number | null>(null);

  const handleCitationClick = (n: number) => {
    setShowSources(true);
    setFocusSource(n);
    // requestAnimationFrame: chờ panel nguồn render xong rồi mới cuộn tới.
    requestAnimationFrame(() => {
      document
        .getElementById(`msg-${message.id}-src-${n}`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
    window.setTimeout(() => setFocusSource(null), 2500);
  };

  const validSources = React.useMemo(
    () =>
      new Set(
        (message.sources || [])
          .map((s) => s.n)
          .filter((n): n is number => typeof n === 'number'),
      ),
    [message.sources],
  );
  // Số nguồn THẬT SỰ được dẫn trong câu trả lời — panel nguồn xếp chúng lên
  // đầu, phần bot đọc mà không dẫn thu gọn lại.
  const citedSources = React.useMemo(() => {
    const out = new Set<number>();
    for (const m of (message.text || '').matchAll(CITE_RE)) out.add(parseInt(m[1], 10));
    return out;
  }, [message.text]);

  const canReport = !isUser && !isError && typeof message.serverMessageId === 'number';
  // Chỉ cho ghi chú / báo cáo khi câu trả lời đã viết xong — lưu bản dở dang
  // vào ghi chú thì vô nghĩa.
  const canNote = !isUser && !isError && !message.isStreaming;
  const [noteOpen, setNoteOpen] = useState(false);
  const [note, setNote] = useState('');
  const [sent, setSent] = useState<null | 'good' | 'bad'>(null);
  const [sending, setSending] = useState(false);
  const [feedbackId, setFeedbackId] = useState<number | null>(null);
  const [notedId, setNotedId] = useState<number | null>(null);
  const groundingMeta = (() => {
    switch (message.grounding_status) {
      case 'grounded':
      case 'verified':
        return {
          label: 'Đã kiểm chứng theo nguồn',
          cls: 'bg-emerald-50 dark:bg-emerald-950/50 text-emerald-800 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800',
        };
      case 'partial':
        return {
          label: 'Chỉ một phần có đủ căn cứ',
          cls: 'bg-amber-50 dark:bg-amber-950/50 text-amber-800 dark:text-amber-300 border-amber-200 dark:border-amber-800',
        };
      case 'uncited':
        return {
          label: 'Chưa gắn được trích dẫn',
          cls: 'bg-amber-50 dark:bg-amber-950/50 text-amber-800 dark:text-amber-300 border-amber-200 dark:border-amber-800',
        };
      // Đã đối chiếu từng đoạn với nguồn mà không đoạn nào khớp → nội dung sinh
      // ra không nằm trong tài liệu. Đây là cảnh báo nặng, giữ màu đỏ.
      case 'uncited_blocked':
        return {
          label: 'Không tìm thấy căn cứ trong nguồn',
          cls: 'bg-red-50 dark:bg-red-950/50 text-red-800 dark:text-red-300 border-red-200 dark:border-red-800',
        };
      case 'insufficient':
        return {
          label: 'Chưa đủ bằng chứng để kết luận',
          cls: 'bg-amber-50 dark:bg-amber-950/50 text-amber-800 dark:text-amber-300 border-amber-200 dark:border-amber-800',
        };
      default:
        return null;
    }
  })();
  const answerModeLabel: Record<string, string> = {
    structured: 'Dữ liệu hệ thống',
    operational: 'Dữ liệu vận hành',
    grounded: 'Tra cứu tài liệu',
    mixed: 'Dữ liệu + tài liệu',
    insufficient_evidence: 'Không đủ bằng chứng',
    chat: 'Hội thoại',
  };

  const handleSaveNote = async () => {
    try {
      const created = await saveNote(message.text.slice(0, 4000), message.serverMessageId ?? null);
      setNotedId(created.id);
      showToast('Đã lưu vào ghi chú của bạn.', 'success');
    } catch (err: any) {
      showToast(err?.message || 'Không lưu được ghi chú.', 'error');
    }
  };

  const downloadSource = async (docId: number, title: string) => {
    try {
      await api.downloadDocument(docId, title);
    } catch (err: any) {
      showToast(err?.message || 'Không tải được tài liệu này.', 'error');
    }
  };

  const previewSource = async (docId: number) => {
    try {
      await api.previewDocument(docId);
    } catch (err: any) {
      // 409 = định dạng chưa có bản xem trước — máy chủ đã gợi ý dùng Tải về.
      showToast(err?.message || 'Không mở được bản xem trước.', 'error');
    }
  };

  // File đã tạo từ chat (luồng "Tạo file mẫu" / "Tạo bộ file"): token nằm
  // trong evidence hệ thống — có thể NHIỀU file một tin nhắn (bộ giấy đề nghị
  // thanh toán + biên bản nghiệm thu). Đặt ở đây — bộ render tin nhắn dùng
  // chung — để nút tải hiện cả khi hội thoại được mở lại từ lịch sử ở tab
  // Hội thoại AI, không chỉ ở tab Kiểm tra pháp lý lúc vừa tạo xong.
  const fillSources = (message.sources || []).filter(
    (s) =>
      typeof s.source_locator === 'string' && s.source_locator.startsWith('template_fill#')
  );
  const [fillBusyToken, setFillBusyToken] = useState<string | null>(null);
  const downloadFill = async (src: (typeof fillSources)[number]) => {
    const token = (src.source_locator as string).split('#', 2)[1] || '';
    if (!token || fillBusyToken) return;
    setFillBusyToken(token);
    try {
      await api.downloadTemplateFill(token, (src.quote as string) || 'file-da-tao.docx');
    } catch (err: any) {
      showToast(err?.message || 'Không tải được file đã tạo.', 'error');
    } finally {
      setFillBusyToken(null);
    }
  };

  const undoNote = async () => {
    if (notedId == null) return;
    try {
      await removeNote(notedId);
      setNotedId(null);
    } catch (err: any) {
      showToast(err?.message || 'Không hoàn tác được.', 'error');
    }
  };

  const submitFeedback = async (rating: 'good' | 'bad', withNote = '') => {
    if (!message.serverMessageId || sending) return;
    setSending(true);
    try {
      const res = await api.sendFeedback({ message_id: message.serverMessageId, rating, note: withNote });
      setSent(rating);
      setFeedbackId(typeof res?.feedback_id === 'number' ? res.feedback_id : null);
      setNoteOpen(false);
    } catch (err: any) {
      showToast(err?.message || 'Không gửi được báo cáo.', 'error');
    } finally {
      setSending(false);
    }
  };

  const undoFeedback = async () => {
    if (feedbackId == null) {
      setSent(null);
      return;
    }
    try {
      await api.retractFeedback(feedbackId);
      setSent(null);
      setFeedbackId(null);
    } catch (err: any) {
      showToast(err?.message || 'Không hoàn tác được (có thể đã được xử lý).', 'error');
    }
  };

  const rowBg = isError
    ? 'bg-red-50/70 dark:bg-red-950/30'
    : isUser
    ? 'bg-slate-50/80 dark:bg-slate-800/40'
    : 'bg-white dark:bg-slate-900';

  // Tin nhắn NGƯỜI DÙNG: bong bóng căn PHẢI như ứng dụng nhắn tin
  if (isUser) {
    return (
      <div
        id={message.serverMessageId ? `chatmsg-${message.serverMessageId}` : undefined}
        className="py-3 px-4 sm:px-6 rounded-lg transition-shadow"
      >
        <div className="max-w-3xl mx-auto flex justify-end">
          <div className="flex items-end gap-2.5 flex-row-reverse max-w-[85%]">
            <div className="w-8 h-8 rounded-xl flex items-center justify-center shrink-0 shadow-sm bg-slate-700 dark:bg-slate-600 text-white">
              <User className="w-4 h-4" />
            </div>
            <div className="min-w-0">
              <div className="bg-hds-navy text-white rounded-2xl rounded-br-sm px-4 py-2.5 shadow-sm">
                <p className="text-sm leading-relaxed whitespace-pre-wrap break-words">
                  {message.text}
                </p>
              </div>
              <div className="flex items-center justify-end gap-2 mt-1 pr-1 text-[10px] text-slate-400 dark:text-slate-500">
                {usedFiles.length > 0 && (
                  <span className="flex items-center gap-0.5 truncate">
                    <FileText className="w-3 h-3 shrink-0" />
                    <span className="truncate">{usedFiles.join(', ')}</span>
                  </span>
                )}
                <span>{message.timestamp}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Tin nhắn TRỢ LÝ (và lỗi): căn TRÁI, có avatar + nguồn + thao tác
  return (
    <div
      id={message.serverMessageId ? `chatmsg-${message.serverMessageId}` : undefined}
      className={`group py-5 px-4 sm:px-6 border-b border-slate-100 dark:border-slate-800 rounded-lg transition-shadow ${rowBg}`}
    >
      <div className="max-w-3xl mx-auto flex items-start gap-3.5">
        <div
          className={`w-8 h-8 rounded-xl flex items-center justify-center shrink-0 shadow-sm ${
            isError
              ? 'bg-hds-red text-white'
              : 'bg-hds-navy text-hds-gold border border-hds-gold/40'
          }`}
        >
          {isError ? <AlertTriangle className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
        </div>

        <div className="flex-1 space-y-2 min-w-0">
          <div className="flex items-center justify-between gap-3 text-xs">
            <span className="font-semibold text-slate-800 dark:text-slate-100">
              {isUser ? 'Bạn' : 'Trợ lý AI HDS'}
            </span>

            <div className="flex items-center gap-2 text-[11px] text-slate-400 dark:text-slate-500 shrink-0">
              {typeof message.latency_ms === 'number' && (
                <button
                  type="button"
                  onClick={() => setShowTiming((v) => !v)}
                  className={`flex items-center gap-1 font-mono rounded px-1 -mx-1 hover:bg-slate-100 dark:hover:bg-slate-800 ${
                    message.latency_ms > 20000 ? 'text-amber-600 dark:text-amber-400 font-bold' : ''
                  }`}
                  title="Bấm để xem thời gian đi vào đâu"
                >
                  <Clock className="w-3 h-3" />
                  {fmtSec(message.latency_ms)}
                </button>
              )}
              <span>{message.timestamp}</span>
            </div>
          </div>

          {showTiming && message.timings && <TimingPanel t={message.timings} />}

          {(message.used_method || usedFiles.length > 0) && (
            <div className="flex flex-wrap gap-1.5 text-[10px] font-medium">
              {message.used_method && (
                <span className="bg-amber-100 dark:bg-amber-950/60 text-amber-900 dark:text-amber-200 border border-amber-300 dark:border-amber-800 px-2 py-0.5 rounded-md flex items-center gap-1">
                  <Sliders className="w-3 h-3" />
                  Áp dụng mẫu phương pháp
                </span>
              )}
              {usedFiles.map((name) => (
                <span
                  key={name}
                  className="bg-blue-100 dark:bg-blue-950/60 text-blue-900 dark:text-blue-200 border border-blue-300 dark:border-blue-800 px-2 py-0.5 rounded-md flex items-center gap-1 max-w-full"
                >
                  <FileText className="w-3 h-3 shrink-0" />
                  <span className="truncate">{name}</span>
                </span>
              ))}
            </div>
          )}

          {!message.isStreaming && groundingMeta && (
            <div
              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-[10px] font-bold ${groundingMeta.cls}`}
            >
              {message.grounding_status === 'grounded' || message.grounding_status === 'verified' ? (
                <CheckCircle2 className="w-3.5 h-3.5" />
              ) : (
                <AlertTriangle className="w-3.5 h-3.5" />
              )}
              {groundingMeta.label}
            </div>
          )}

          {!message.isStreaming && message.answer_mode && answerModeLabel[message.answer_mode] && (
            <div className="inline-flex items-center gap-1.5 ml-1.5 px-2.5 py-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-300 text-[10px] font-semibold">
              <FileText className="w-3.5 h-3.5" />
              {answerModeLabel[message.answer_mode]}
            </div>
          )}

          {/* Giai đoạn ĐỌC tài liệu: đã có nguồn nhưng model chưa viết chữ nào.
              Trên máy CPU quãng này dài cả trăm giây; hiện lời nhắc động để
              người dùng biết hệ thống đang chạy chứ không treo. */}
          {message.isStreaming && !message.text ? (
            <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
              {/* Mốc tiến trình do máy chủ phát (sự kiện 'status') — cụ thể hoá
                  từng chặng: tìm kho, tra luật, đọc file mẫu… */}
              <span>{message.statusLabel || 'Đang đọc tài liệu và soạn câu trả lời'}</span>
              <span className="flex gap-0.5">
                <span className="w-1.5 h-1.5 rounded-full bg-hds-navy dark:bg-blue-400 animate-bounce [animation-delay:-0.3s]" />
                <span className="w-1.5 h-1.5 rounded-full bg-hds-navy dark:bg-blue-400 animate-bounce [animation-delay:-0.15s]" />
                <span className="w-1.5 h-1.5 rounded-full bg-hds-navy dark:bg-blue-400 animate-bounce" />
              </span>
            </div>
          ) : (
            <div
              className={
                isError
                  ? 'text-sm leading-relaxed whitespace-pre-wrap break-words text-red-800 dark:text-red-200 font-medium'
                  : 'text-slate-800 dark:text-slate-200'
              }
            >
              {isUser || isError ? (
                <span className="text-sm leading-relaxed whitespace-pre-wrap break-words">
                  {message.text}
                </span>
              ) : (
                /* Bot: render markdown + chip nguồn bấm được, kiểu NotebookLM.
                   Trong lúc streaming vẫn render được — mỗi delta chỉ là chuỗi
                   dài thêm, renderer parse lại từ đầu (vài nghìn ký tự, không
                   đáng kể). */
                <MessageMarkdown
                  text={message.text}
                  onCitationClick={handleCitationClick}
                  validSources={validSources}
                />
              )}
              {/* Con trỏ nhấp nháy trong lúc chữ còn đang chảy về */}
              {message.isStreaming && (
                <span
                  className="inline-block w-[2px] h-[1em] align-text-bottom ml-0.5 bg-hds-navy dark:bg-blue-400 animate-pulse"
                  aria-label="Đang viết"
                />
              )}
              {/* Sau khi chữ đã chảy xong vẫn còn bước soát lại — hiện mốc để
                  người dùng biết vì sao câu trả lời chưa "chốt". */}
              {message.isStreaming && message.text && message.statusLabel && (
                <div className="mt-2 flex items-center gap-2 text-xs italic text-slate-500 dark:text-slate-400">
                  <span className="w-1.5 h-1.5 rounded-full bg-hds-gold animate-pulse" />
                  {message.statusLabel}
                </div>
              )}
            </div>
          )}

          {/* Nút tải các file đã tạo từ chat (điền mẫu / tạo bộ file) */}
          {!isUser && !message.isStreaming && fillSources.length > 0 && (
            <div className="mt-2 flex flex-col gap-1.5">
              {fillSources.map((src, i) => {
                const token = (src.source_locator as string).split('#', 2)[1] || '';
                const quote = (src.quote as string) || '';
                // Gói .zip cả bộ (bộ mẫu nhiều file) — nút nổi bật hơn nút lẻ.
                const laZip = /\.zip$/i.test(quote);
                const label = laZip
                  ? `${(src.title as string) || 'Tải cả bộ'} (.zip)`
                  : fillSources.length === 1
                    ? 'Tải file đã điền (.docx)'
                    : `Tải: ${quote || `file ${i + 1}`}`;
                return (
                  <button
                    key={token || i}
                    type="button"
                    onClick={() => void downloadFill(src)}
                    disabled={fillBusyToken !== null}
                    className={`self-start inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold disabled:opacity-60 transition-colors max-w-full ${
                      laZip
                        ? 'bg-hds-gold text-hds-navy hover:bg-hds-gold-light'
                        : 'bg-hds-navy text-hds-gold hover:bg-hds-navy-light'
                    }`}
                  >
                    {fillBusyToken === token ? (
                      <span className="w-3.5 h-3.5 shrink-0 rounded-full border-2 border-hds-gold border-t-transparent animate-spin" />
                    ) : (
                      <Download className="w-3.5 h-3.5 shrink-0" />
                    )}
                    <span className="truncate">{label}</span>
                  </button>
                );
              })}
            </div>
          )}

          {/* Nguồn chỉ hiện khi câu trả lời đã xong — trong lúc đọc/soạn chỉ có
              một dòng "đang đọc tài liệu…". Gom theo tài liệu: xem SourcePanel. */}
          {!isUser && !message.isStreaming && message.sources && message.sources.length > 0 && (
            <SourcePanel
              sources={message.sources}
              messageId={message.id}
              open={showSources}
              onToggle={() => setShowSources((v) => !v)}
              focusN={focusSource}
              cited={citedSources}
              onPreview={previewSource}
              onDownload={downloadSource}
            />
          )}

          {/* Hàng thao tác: lưu ghi chú + báo cáo chất lượng — mỗi cái có Hoàn tác */}
          {canNote && (
            <div className="flex flex-wrap items-center gap-x-1 gap-y-1.5 pt-1 opacity-50 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
              {/* Lưu note / đã ghi chú + hoàn tác */}
              {notedId == null ? (
                <button
                  onClick={handleSaveNote}
                  title="Lưu câu trả lời này vào ghi chú"
                  aria-label="Lưu vào ghi chú"
                  className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-semibold text-slate-500 dark:text-slate-400 hover:text-hds-navy dark:hover:text-blue-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                >
                  <StickyNote className="w-3.5 h-3.5" />
                  Lưu note
                </button>
              ) : (
                <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-hds-green dark:text-emerald-400">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  Đã ghi chú
                  <button
                    onClick={undoNote}
                    className="text-slate-500 dark:text-slate-400 hover:text-hds-navy dark:hover:text-blue-300 inline-flex items-center gap-0.5"
                  >
                    <Undo2 className="w-3 h-3" />
                    Hoàn tác
                  </button>
                </span>
              )}

              {canReport && (
                <>
                  <span className="w-px h-4 bg-slate-200 dark:bg-slate-700 mx-1" />
                  {sent ? (
                    <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-slate-500 dark:text-slate-400">
                      {sent === 'good' ? (
                        <>
                          <ThumbsUp className="w-3.5 h-3.5 text-hds-green" />
                          Cảm ơn đánh giá
                        </>
                      ) : (
                        <>
                          <CheckCircle2 className="w-3.5 h-3.5 text-hds-green" />
                          Đã gửi báo cáo
                        </>
                      )}
                      <button
                        onClick={undoFeedback}
                        className="hover:text-hds-navy dark:hover:text-blue-300 inline-flex items-center gap-0.5"
                      >
                        <Undo2 className="w-3 h-3" />
                        Hoàn tác
                      </button>
                    </span>
                  ) : (
                    <>
                      <button
                        onClick={() => submitFeedback('good')}
                        disabled={sending}
                        title="Câu trả lời tốt"
                        aria-label="Báo cáo: câu trả lời tốt"
                        className="p-1.5 rounded-lg text-slate-400 hover:text-hds-green hover:bg-emerald-50 dark:hover:bg-emerald-950/40 transition-colors"
                      >
                        <ThumbsUp className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => setNoteOpen(true)}
                        disabled={sending}
                        title="Báo cáo câu trả lời chưa ổn"
                        aria-label="Báo cáo: câu trả lời chưa tốt"
                        className="p-1.5 rounded-lg text-slate-400 hover:text-hds-red hover:bg-red-50 dark:hover:bg-red-950/40 transition-colors"
                      >
                        <ThumbsDown className="w-3.5 h-3.5" />
                      </button>
                    </>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Popup báo cáo — mở khi bấm 👎 */}
      {noteOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onClick={() => {
            setNoteOpen(false);
            setNote('');
          }}
        >
          <div
            className="bg-white dark:bg-slate-900 rounded-2xl shadow-xl border border-slate-200 dark:border-slate-800 w-full max-w-md p-5 space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start gap-3">
              <span className="p-2 bg-red-50 dark:bg-red-950 text-hds-red rounded-xl shrink-0">
                <Flag className="w-5 h-5" />
              </span>
              <div>
                <h3 className="font-bold text-sm text-slate-900 dark:text-slate-100">
                  Báo cáo câu trả lời chưa ổn
                </h3>
                <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5 leading-relaxed">
                  Ghi rõ sai ở đâu, thiếu căn cứ nào. Quản trị sẽ sửa lại và dạy AI để lần sau gặp
                  câu tương tự trả lời đúng.
                </p>
              </div>
            </div>
            <textarea
              rows={4}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              autoFocus
              placeholder="Ví dụ: trả lời sai điều luật áp dụng, cần dẫn Điều 159 Luật Doanh nghiệp 2020…"
              className="w-full px-3 py-2 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-xl text-xs focus:ring-2 focus:ring-hds-blue focus:outline-none resize-y"
            />
            <div className="flex items-center justify-end gap-2">
              <button
                onClick={() => {
                  setNoteOpen(false);
                  setNote('');
                }}
                className="px-3.5 py-2 rounded-xl text-xs font-medium text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              >
                Huỷ
              </button>
              <button
                onClick={() => submitFeedback('bad', note)}
                disabled={sending}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold text-white bg-hds-red hover:bg-red-800 disabled:opacity-50 transition-colors"
              >
                <Send className="w-3.5 h-3.5" />
                {sending ? 'Đang gửi…' : 'Gửi báo cáo'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
