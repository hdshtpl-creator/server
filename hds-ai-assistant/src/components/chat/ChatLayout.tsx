import React, { useState, useRef, useEffect } from 'react';
import { useApp } from '../../context/AppContext';
import { ConversationSidebar } from './ConversationSidebar';
import { ChatMessageItem } from './ChatMessageItem';
import * as api from '../../api';
import type { BrowseDocument, MethodTemplate, TempAttachment } from '../../types';
import { isClientRole, ATTACH_ACCEPT_FALLBACK } from '../../constants';
import {
  Send,
  Square,
  Paperclip,
  Sliders,
  FileText,
  X,
  Loader2,
  Sparkles,
  AlertCircle,
  AlertTriangle,
  Bot,
  Cpu,
  BookOpen,
  Check,
  Search,
} from 'lucide-react';

const nowLabel = () =>
  new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });

/**
 * Tay cầm cắt lượt trả lời đang chạy — để Ở MỨC MODULE, không phải useRef.
 *
 * App.tsx render khung chat trong một ternary theo `activeView`, nên bấm sang
 * Quản trị / Kiểm tra pháp lý là component bị THÁO HẲN. Cờ `isChatStreaming`
 * thì nằm ở AppContext nên sống tiếp; nếu tay cầm nằm trong useRef thì bản
 * gắn lại có ref RỖNG: ô nhập vẫn khoá, nút Dừng hiện ra nhưng bấm KHÔNG ăn
 * gì — đúng cảnh "khung chat mờ, không gõ được". Ở mức module thì bản nào
 * đang gắn cũng cắt được đúng lượt đang chạy.
 */
let luotDangChay: AbortController | null = null;

export const ChatLayout: React.FC = () => {
  const {
    activeConversation,
    activeConvId,
    addMessageToConv,
    updateMessage,
    setConvServerId,
    setConvAttachments,
    currentUser,
    isChatStreaming,
    setChatStreaming,
    showToast,
  } = useApp();

  const [inputQuestion, setInputQuestion] = useState('');
  const [useMethod, setUseMethod] = useState(false);
  const [methodTemplates, setMethodTemplates] = useState<MethodTemplate[]>([]);
  const [genModels, setGenModels] = useState<string[]>([]);
  // Model gọi qua API ngoài. Chỉ hiện khi admin ĐÃ BẬT nhánh này — chọn một
  // model cloud lúc nó đang tắt thì máy chủ tự trả về Qwen local, người hỏi
  // không hiểu vì sao câu trả lời khác hẳn mong đợi.
  const [cloudModels, setCloudModels] = useState<string[]>([]);
  const [warmModels, setWarmModels] = useState<string[]>([]);
  // 'auto' = fast-path cho câu xác định, model chất lượng mặc định cho RAG;
  // '' = mặc định máy chủ; hoặc tên model cụ thể
  const [selectedModel, setSelectedModel] = useState('auto');
  const [uploading, setUploading] = useState(false);
  // Nhịp đập mỗi giây trong lúc đọc file, chỉ để chip đếm giây hiện ra là còn
  // sống. Không chạy khi rảnh nên không tốn gì.
  const [nhip, setNhip] = useState(0);
  const [isDragging, setDragging] = useState(false);
  // Danh sách đuôi file lấy TỪ MÁY CHỦ (GET /upload/formats). Chép tay vào
  // giao diện là có ngày hộp thoại chặn đúng file mà máy chủ đọc được.
  const [acceptExts, setAcceptExts] = useState<string>(ATTACH_ACCEPT_FALLBACK);
  const [showSourcePicker, setShowSourcePicker] = useState(false);
  const [sourceDocs, setSourceDocs] = useState<BrowseDocument[]>([]);
  const [sourceQuery, setSourceQuery] = useState('');
  const [selectedSourceIds, setSelectedSourceIds] = useState<number[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [quota, setQuota] = useState<{ used: number; limit: number } | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // Hội thoại đang được tạo — giữ Ở REF để hai file thả cùng lúc dùng CHUNG
  // một mã hội thoại thay vì đẻ ra hai cuộc trò chuyện rỗng.
  const convPromiseRef = useRef<Promise<number> | null>(null);
  // Mã hội thoại đang mở, đọc được từ trong hàm bất đồng bộ (state trong
  // closure là bản cũ). Dùng để biết người dùng đã chuyển sang cuộc khác
  // giữa lúc file còn đang tải.
  const openConvRef = useRef<number | null>(null);
  // Bộ đếm sự kiện dragenter/dragleave: kéo qua các phần tử con cũng bắn
  // dragleave, đếm mới biết chuột đã thật sự rời khung hay chưa.
  const dragDepthRef = useRef(0);

  const isClient = isClientRole(currentUser?.role);
  const serverConvId = activeConversation?.server_id;
  const attachments = activeConversation?.attachments ?? [];
  // Chỉ nhân viên nội bộ: /upload/extract nằm sau require(INTERNAL_ROLES).
  const canUpload = !isClient;

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [activeConversation?.messages, isChatStreaming]);

  // Mã hội thoại đổi (chọn cuộc khác ở cột trái, hoặc bấm "cuộc mới") → bỏ
  // lời hứa tạo hội thoại cũ, nếu không file thả vào cuộc mới sẽ chui vào
  // cuộc trước đó.
  useEffect(() => {
    convPromiseRef.current = serverConvId != null ? Promise.resolve(serverConvId) : null;
    openConvRef.current = serverConvId ?? null;
  }, [serverConvId, activeConvId]);

  useEffect(() => {
    if (isClient) return;
    api
      .getUploadFormats()
      .then((res) => {
        const exts = (res?.extensions || []).filter((e) => typeof e === 'string');
        if (exts.length) setAcceptExts(exts.join(','));
      })
      .catch(() => {
        /* im lặng — đã có danh sách dự phòng, máy chủ vẫn là chốt cuối */
      });
  }, [isClient]);

  const openSourcePicker = async () => {
    setShowSourcePicker(true);
  };

  // Tìm trên server thay vì chỉ lọc 300 dòng đầu. Với kho lớn, nhập tên/mã
  // tài liệu vẫn tìm được nguồn nằm ngoài trang đầu.
  useEffect(() => {
    if (!showSourcePicker || isClient) return;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      setSourcesLoading(true);
      try {
        const docs = await api.getBrowseDocuments({ q: sourceQuery.trim() });
        if (!cancelled) {
          setSourceDocs((Array.isArray(docs) ? docs : []).filter((doc) => doc.can_open));
        }
      } catch (err: any) {
        if (!cancelled) setErrorMessage(err?.message || 'Không tải được danh sách nguồn.');
      } finally {
        if (!cancelled) setSourcesLoading(false);
      }
    }, sourceQuery.trim() ? 250 : 0);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [showSourcePicker, sourceQuery, isClient]);

  // Bộ nguồn là phạm vi của hội thoại hiện tại. Đổi hội thoại phải bỏ lựa chọn
  // cũ để không vô tình giới hạn câu hỏi mới vào hồ sơ của cuộc chat trước.
  useEffect(() => {
    setSelectedSourceIds([]);
    setSourceQuery('');
  }, [activeConvId]);

  const refreshModels = () => {
    if (isClient) return;
    api.getModels().then((m) => {
      setGenModels(Array.isArray(m?.generation) ? m.generation : []);
      setWarmModels(Array.isArray(m?.loaded) ? m.loaded : []);
      setCloudModels(m?.cloud_enabled && Array.isArray(m?.cloud) ? m.cloud : []);
    }).catch(() => undefined);
  };

  useEffect(() => {
    if (isClient) return;
    api
      .getMethods()
      .then((templates) => setMethodTemplates(Array.isArray(templates) ? templates : []))
      .catch(() => setMethodTemplates([]));
    // Danh sách model để chọn ngay ô chat (chỉ nhân viên nội bộ)
    refreshModels();
    // refreshModels chỉ phụ thuộc vai hiện tại; gọi lại khi isClient đổi.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isClient]);

  /**
   * Mã hội thoại có thật để gắn file vào — tạo trước nếu chưa có.
   *
   * Luồng cũ bắt gửi một câu hỏi trước rồi mới đính kèm được. Ở đây làm như
   * Claude/ChatGPT: kéo file vào là xong, hội thoại tự sinh. Lời hứa giữ ở ref
   * nên thả năm file cùng lúc vẫn chỉ tạo MỘT hội thoại.
   */
  const ensureConversation = async (): Promise<number> => {
    if (serverConvId != null) return serverConvId;
    if (!convPromiseRef.current) {
      convPromiseRef.current = api
        .createConversation('chat')
        .then((res) => {
          setConvServerId(activeConvId, res.conversation_id);
          return res.conversation_id;
        })
        .catch((err) => {
          convPromiseRef.current = null; // lần sau thử lại được
          throw err;
        });
    }
    return convPromiseRef.current;
  };

  /**
   * Đính kèm file vào hội thoại: MÁY CHỦ đọc, không phải trình duyệt.
   *
   * Nhờ vậy .pdf/.docx/ảnh scan đều dùng được — trình duyệt chỉ đọc nổi văn
   * bản thuần. File không vào kho tri thức, tự xoá sau 6 giờ.
   */
  const handleAttach = async (files: FileList | File[] | null) => {
    const list = files ? Array.from(files) : [];
    if (!list.length || !canUpload) return;
    setUploading(true);
    setErrorMessage(null);
    try {
      const conv = await ensureConversation();
      for (const file of list) {
        // Chip "đang đọc" hiện NGAY: OCR một bản scan mất hàng chục giây, im
        // lặng suốt quãng đó là người dùng tưởng cú thả file rơi vào hư không.
        const pending: TempAttachment = {
          id: null,
          filename: file.name,
          chunks: 0,
          status: 'uploading',
          warnings: [],
          textChars: 0,
          startedAt: Date.now(),
        };
        setConvAttachments(conv, (prev) => [...prev, pending]);
        try {
          const res = await api.uploadExtract({ conversation_id: conv, file });
          setConvAttachments(conv, (prev) =>
            prev.map((a) =>
              a === pending
                ? {
                    id: typeof res.temp_file_id === 'number' ? res.temp_file_id : null,
                    filename: res.filename || file.name,
                    chunks: res.chunks || 0,
                    status: res.status || 'ok',
                    warnings: Array.isArray(res.warnings) ? res.warnings : [],
                    textChars: typeof res.text_chars === 'number' ? res.text_chars : 0,
                  }
                : a
            )
          );
          // Người dùng đã bấm sang cuộc trò chuyện khác trong lúc máy chủ còn
          // đang đọc file: chip không mọc ở màn hình đang mở (cố ý — hồ sơ
          // khách không được lẫn sang cuộc khác), nhưng file ĐÃ nằm trong
          // cuộc kia. Nói thẳng ra, đừng để nó biến mất không dấu vết.
          // null = màn hình chưa kịp dựng lại sau khi hội thoại vừa được tạo,
          // chưa biết gì thì đừng báo — báo nhầm còn khó hiểu hơn im lặng.
          if (openConvRef.current != null && openConvRef.current !== conv) {
            showToast(
              `«${file.name}» đã đính kèm vào cuộc trò chuyện trước đó — ` +
                'mở lại cuộc đó để hỏi về file này.',
              'info'
            );
          }
        } catch (err: any) {
          // Bỏ đúng chip tạm của file hỏng, giữ nguyên các file đọc được.
          setConvAttachments(conv, (prev) => prev.filter((a) => a !== pending));
          showToast(err?.message || `Không đọc được «${file.name}».`, 'error');
        }
      }
    } catch (err: any) {
      showToast(err?.message || 'Không mở được hội thoại để đính kèm file.', 'error');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  /**
   * Gỡ file đính kèm — xoá THẬT trên máy chủ, không chỉ ẩn chip.
   *
   * Bản trước chỉ xoá state cục bộ: bản ghi temp_files vẫn còn, nên lượt hỏi
   * sau bot vẫn đọc lại đúng tài liệu người dùng tưởng đã gỡ. Hồ sơ khách gỡ
   * nhầm rồi vẫn nằm trong ngữ cảnh là chuyện không chấp nhận được ở một hãng
   * luật.
   */
  const removeAttachment = async (target: TempAttachment) => {
    if (serverConvId == null) return;
    if (target.id != null) {
      try {
        await api.deleteTempFile(target.id);
      } catch (err: any) {
        showToast(err?.message || `Không gỡ được «${target.filename}» trên máy chủ.`, 'error');
        return; // giữ chip để người dùng biết file vẫn còn
      }
    }
    // Lọc theo CHÍNH đối tượng đó, không theo chỉ số: giữa lúc chờ máy chủ xoá,
    // một lượt tải khác có thể đã chèn thêm chip và làm lệch chỉ số.
    setConvAttachments(serverConvId, (prev) => prev.filter((a) => a !== target));
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    dragDepthRef.current = 0;
    setDragging(false);
    if (!canUpload) return;
    void handleAttach(e.dataTransfer?.files ?? null);
  };

  /** Dán ảnh chụp màn hình / file từ clipboard thẳng vào ô hỏi. */
  useEffect(() => {
    if (!uploading) return;
    const t = window.setInterval(() => setNhip((n) => n + 1), 1000);
    return () => window.clearInterval(t);
  }, [uploading]);

  const handlePaste = (e: React.ClipboardEvent) => {
    const files = Array.from(e.clipboardData?.files || []);
    if (!files.length || !canUpload) return; // dán chữ bình thường thì không đụng vào
    e.preventDefault();
    void handleAttach(files);
  };

  const handleSendMessage = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const questionText = inputQuestion.trim();
    if (!questionText || isChatStreaming || !activeConversation) return;
    // File còn đang đọc thì CHẶN, đừng gửi câu hỏi đi tay không. Bản trước chỉ
    // loại chip 'uploading' ra khỏi danh sách tên file rồi vẫn gửi: người dùng
    // thả hợp đồng vào, gõ "tóm tắt", và nhận về một câu trả lời soạn từ hư
    // không vì máy chủ chưa có chữ nào của file đó (ca thật 29/08/2026 — bot
    // đáp lại chính câu nhắn hệ thống thay vì tài liệu).
    if (uploading) {
      showToast('Đang đọc file đính kèm — chờ đọc xong rồi hỏi, không thì bot trả lời khi chưa có nội dung file.', 'info');
      return;
    }

    setInputQuestion('');
    setErrorMessage(null);

    // Chỉ tính các file đã đọc xong: chip còn "uploading" chưa có nội dung
    // trên máy chủ, ghi tên nó vào lượt hỏi là nói dối người dùng.
    const readyNames = attachments
      .filter((a) => a.status !== 'uploading')
      .map((a) => a.filename);

    addMessageToConv(activeConvId, {
      id: `msg-${Date.now()}`,
      sender: 'user',
      text: questionText,
      timestamp: nowLabel(),
      used_method: useMethod && !isClient,
      used_temp_files: readyNames.length ? readyNames : undefined,
    });

    setChatStreaming(true);
    // Tay cầm để nút "Dừng" cắt đúng lượt này. Đóng kết nối cũng là tín hiệu
    // dừng gửi tới máy chủ — model ngừng viết ngay, không viết nốt cho không.
    const stopper = new AbortController();
    luotDangChay = stopper;
    // Ô trống cho câu trả lời, chữ sẽ chảy dần vào đây.
    const aiMsgId = `ai-${Date.now()}`;
    let opened = false;

    try {
      await api.chatStream(
        {
          question: questionText,
          conversation_id: serverConvId ?? null,
          use_temp: readyNames.length > 0,
          use_method: useMethod && !isClient,
          model: isClient ? undefined : selectedModel,
          source_document_ids:
            isClient || selectedSourceIds.length === 0 ? undefined : selectedSourceIds,
          signal: stopper.signal,
        },
        (evt) => {
          if (evt.type === 'start' && evt.conversation_id) {
            // Ghi nhớ mã hội thoại do backend cấp để các lượt sau nối đúng ngữ cảnh.
            setConvServerId(activeConvId, evt.conversation_id);
            // Dựng bong bóng NGAY từ đây (trước cả meta) để các mốc tiến trình
            // 'status' phát trong lúc máy chủ tìm kho có chỗ hiển thị — máy
            // chậm mà màn hình im lặng là người dùng tưởng treo.
            addMessageToConv(activeConvId, {
              id: aiMsgId,
              sender: 'ai',
              text: '',
              timestamp: nowLabel(),
              isStreaming: true,
              statusLabel: 'Đang chuẩn bị…',
            });
            opened = true;
            return;
          }
          if (evt.type === 'status' && evt.label) {
            const label = evt.label;
            updateMessage(aiMsgId, (m) => ({ ...m, statusLabel: label }));
            return;
          }
          if (evt.type === 'meta') {
            // Nguồn trích dẫn đã biết trước khi model viết chữ nào. Vẫn khoá
            // lượt gửi mới — chỉ `done` mới xác nhận backend đã lưu xong.
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
            updateMessage(aiMsgId, (m) => ({
              ...m, text: m.text + piece, statusLabel: undefined,
            }));
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
            if (evt.quota) setQuota(evt.quota);
            refreshModels();
            updateMessage(aiMsgId, (m) => ({
              ...m,
              isStreaming: false,
              statusLabel: undefined,
              latency_ms: evt.latency_ms,
              serverMessageId: evt.message_id,
              timings: evt.timings,
              grounding_status: evt.grounding_status ?? m.grounding_status,
              answer_mode: evt.answer_mode ?? m.answer_mode,
              // Bản nguồn CUỐI đã lọc "chỉ nguồn liên quan" (được trích dẫn /
              // điểm cao) — thay danh sách đầy đủ đã gửi ở meta.
              sources: evt.sources ?? m.sources,
            }));
          }
        }
      );
    } catch (err: any) {
      // Người dùng chủ động bấm "Dừng" — không phải sự cố: giữ nguyên phần
      // chữ đã viết, đóng con trỏ nhấp nháy, KHÔNG hiện băng lỗi đỏ. Máy chủ
      // đã lưu đúng phần này kèm dấu bị cắt, nên mở lại hội thoại vẫn khớp.
      if (err?.code === api.DUNG_BOI_NGUOI_DUNG) {
        updateMessage(aiMsgId, (m) => ({
          ...m,
          isStreaming: false,
          statusLabel: undefined,
          text: m.text
            ? `${m.text}\n\n_(Người dùng đã dừng câu trả lời giữa chừng.)_`
            : 'Đã dừng trước khi AI kịp viết câu nào.',
        }));
        return;
      }
      const errMsg = err?.message || 'Có lỗi xảy ra khi hỏi AI.';
      setErrorMessage(errMsg);
      if (opened) {
        // Đứt giữa chừng: giữ lại phần đã viết, ghi rõ là chưa trọn vẹn — xoá
        // đi thì người dùng mất luôn phần nội dung có thể vẫn dùng được.
        // Bong bóng giờ mở từ sự kiện 'start' nên có thể CHƯA có chữ nào
        // (lỗi ngay trong lúc tìm kho) — khi đó hiện hẳn lỗi, đừng ghép chuỗi
        // vào text rỗng thành một dòng nghiêng khó hiểu.
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
        addMessageToConv(activeConvId, {
          id: `err-${Date.now()}`,
          sender: 'ai',
          text: errMsg,
          timestamp: nowLabel(),
          isError: true,
        });
      }
    } finally {
      // Chỉ dọn nếu vẫn là lượt của mình — lượt mới đã ghi đè thì để yên.
      if (luotDangChay === stopper) luotDangChay = null;
      setChatStreaming(false);
      textareaRef.current?.focus();
    }
  };

  /** Cắt lượt trả lời đang chạy. Đóng kết nối là tín hiệu để máy chủ bật cờ
   *  huỷ và model ngừng sinh chữ — không phải chỉ giấu chữ đi trên màn hình. */
  const handleStop = () => {
    if (luotDangChay) {
      luotDangChay.abort();
      return;
    }
    // Không còn tay cầm mà cờ vẫn bật: lượt cũ đã chết mà quên tắt cờ (ví dụ
    // đăng nhập lại giữa chừng). Mở khoá giao diện — nút Dừng KHÔNG BAO GIỜ
    // được phép bấm mà không có gì xảy ra.
    setChatStreaming(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const messages = activeConversation?.messages ?? [];
  const hasConversation = messages.length > 0;
  const visibleSourceDocs = sourceDocs;

  return (
    <div className="flex w-full h-[calc(100dvh-4rem)] bg-hds-soft dark:bg-slate-950 overflow-hidden">
      <ConversationSidebar />

      <main
        className="relative flex-1 flex flex-col h-full bg-white dark:bg-slate-900 min-w-0"
        onDragEnter={(e) => {
          if (!canUpload || !e.dataTransfer?.types?.includes('Files')) return;
          dragDepthRef.current += 1;
          setDragging(true);
        }}
        onDragOver={(e) => {
          // Không chặn dragover thì trình duyệt tự mở file trong tab và cuộc
          // trò chuyện biến mất — cú thả nào cũng phải bị chặn ở đây.
          if (canUpload && e.dataTransfer?.types?.includes('Files')) e.preventDefault();
        }}
        onDragLeave={() => {
          dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
          if (dragDepthRef.current === 0) setDragging(false);
        }}
        onDrop={handleDrop}
      >
        {isDragging && (
          <div className="absolute inset-0 z-30 flex items-center justify-center bg-hds-navy/10 dark:bg-blue-950/50 border-2 border-dashed border-hds-navy dark:border-blue-400 rounded-xl pointer-events-none">
            <span className="flex items-center gap-2 bg-white dark:bg-slate-900 text-hds-navy dark:text-blue-200 font-bold text-sm px-4 py-2.5 rounded-xl shadow-lg border border-blue-200 dark:border-blue-900">
              <Paperclip className="w-4 h-4" />
              Thả file vào đây để bot đọc
            </span>
          </div>
        )}
        {/* Thanh công cụ trên cùng */}
        <div className="border-b border-slate-200 dark:border-slate-800 px-3 sm:px-4 py-2.5 flex items-center justify-between gap-3 shrink-0">
          <div className="flex items-center gap-2.5 min-w-0">
            <h2 className="font-bold text-sm text-slate-800 dark:text-slate-100 truncate">
              {activeConversation?.title || 'Cuộc trò chuyện'}
            </h2>

            {attachments.length > 0 && (
              <span className="hidden sm:flex items-center gap-1 bg-blue-50 dark:bg-blue-950/60 text-blue-900 dark:text-blue-200 border border-blue-300 dark:border-blue-800 text-[11px] px-2.5 py-1 rounded-full shrink-0">
                <FileText className="w-3.5 h-3.5 shrink-0" />
                <span className="font-medium">
                  {attachments.length} file đính kèm
                </span>
              </span>
            )}
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {/* Hạn mức câu hỏi — chỉ hiện với tài khoản khách hàng */}
            {isClient && quota && (
              <span className="text-[11px] font-semibold px-2.5 py-1 rounded-lg border bg-indigo-50 dark:bg-indigo-950/60 text-indigo-800 dark:text-indigo-300 border-indigo-200 dark:border-indigo-800">
                Đã dùng {quota.used}/{quota.limit} lượt tháng này
              </span>
            )}

            {/* Mẫu phương pháp phân tích */}
            {!isClient && methodTemplates.length > 0 && (
              <label
                htmlFor="use-method-checkbox"
                className="flex items-center gap-1.5 bg-slate-50 dark:bg-slate-800 px-2.5 py-1.5 rounded-xl border border-slate-200 dark:border-slate-700 text-xs cursor-pointer select-none"
                title={methodTemplates.map((m) => m.case_type).join(' • ')}
              >
                <input
                  id="use-method-checkbox"
                  type="checkbox"
                  checked={useMethod}
                  onChange={(e) => setUseMethod(e.target.checked)}
                  className="w-3.5 h-3.5 accent-[#1f3864] cursor-pointer"
                />
                <Sliders className="w-3.5 h-3.5 text-hds-navy dark:text-blue-400" />
                <span className="font-semibold text-slate-700 dark:text-slate-300 hidden sm:inline">
                  Mẫu phương pháp
                </span>
              </label>
            )}

            {!isClient && (
              <button
                type="button"
                onClick={openSourcePicker}
                disabled={isChatStreaming}
                className={`flex items-center gap-1.5 font-semibold text-xs px-3 py-1.5 rounded-xl border transition-colors disabled:opacity-50 ${
                  selectedSourceIds.length > 0
                    ? 'bg-blue-50 dark:bg-blue-950/60 text-hds-navy dark:text-blue-200 border-blue-300 dark:border-blue-800'
                    : 'bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-700'
                }`}
                title="Giới hạn câu trả lời trong các tài liệu đã chọn"
              >
                <BookOpen className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">
                  {selectedSourceIds.length > 0
                    ? `Nguồn đã chọn (${selectedSourceIds.length})`
                    : 'Chọn nguồn'}
                </span>
              </button>
            )}

            {!isClient && (
              <button
                id="chat-upload-btn"
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={!canUpload || uploading}
                className="flex items-center gap-1.5 bg-hds-soft dark:bg-slate-800 text-hds-navy dark:text-blue-300 font-semibold text-xs px-3 py-1.5 rounded-xl border border-blue-200 dark:border-slate-700 hover:bg-blue-100 dark:hover:bg-slate-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                title="Đính kèm file cho bot đọc — mọi định dạng, không vào kho tri thức"
              >
                {uploading ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Paperclip className="w-3.5 h-3.5" />
                )}
                <span className="hidden sm:inline">Đính kèm file</span>
              </button>
            )}
          </div>
        </div>

        {/* Dải báo lỗi */}
        {errorMessage && (
          <div className="bg-red-50 dark:bg-red-950/50 border-b border-red-200 dark:border-red-900 px-4 py-2 text-xs text-red-800 dark:text-red-200 flex items-start justify-between gap-3 shrink-0">
            <span className="flex items-start gap-2">
              <AlertCircle className="w-4 h-4 shrink-0 mt-px" />
              <span>{errorMessage}</span>
            </span>
            <button
              onClick={() => setErrorMessage(null)}
              className="p-0.5 shrink-0"
              aria-label="Đóng thông báo lỗi"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* Danh sách tin nhắn */}
        <div className="flex-1 overflow-y-auto min-h-0">
          {hasConversation ? (
            messages.map((msg) => <ChatMessageItem key={msg.id} message={msg} />)
          ) : (
            <div className="h-full flex flex-col items-center justify-center p-8 text-center">
              <Sparkles className="w-12 h-12 text-hds-navy dark:text-blue-400 mb-3 opacity-40" />
              <h3 className="font-bold text-slate-700 dark:text-slate-200 text-base">
                Trợ lý AI Pháp lý HDS
              </h3>
              <p className="text-xs max-w-sm mt-1 text-slate-500 dark:text-slate-400">
                Đặt câu hỏi pháp lý hoặc kéo thả tài liệu vào đây để tra cứu điều khoản, hợp
                đồng và tiền lệ tư vấn của HDS.
              </p>
            </div>
          )}

          {isChatStreaming && !messages.some((message) => message.isStreaming) && (
            <div className="py-5 px-4 sm:px-6 border-b border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900">
              <div className="max-w-3xl mx-auto flex items-start gap-3.5">
                {/* Avatar trợ lý — giống hệt tin nhắn thật để nhìn ra ngay là bot đang soạn */}
                <div className="w-8 h-8 rounded-xl flex items-center justify-center shrink-0 shadow-sm bg-hds-navy text-hds-gold border border-hds-gold/40">
                  <Bot className="w-4 h-4" />
                </div>
                <div className="min-w-0 pt-1">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-sm text-slate-900 dark:text-slate-100">
                      Trợ lý AI HDS
                    </span>
                    <span className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
                      <span>đang trả lời</span>
                      <span className="flex gap-0.5">
                        <span className="w-1.5 h-1.5 rounded-full bg-hds-navy dark:bg-blue-400 animate-bounce [animation-delay:-0.3s]" />
                        <span className="w-1.5 h-1.5 rounded-full bg-hds-navy dark:bg-blue-400 animate-bounce [animation-delay:-0.15s]" />
                        <span className="w-1.5 h-1.5 rounded-full bg-hds-navy dark:bg-blue-400 animate-bounce" />
                      </span>
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-400 dark:text-slate-500 mt-1">
                    Đang tra cứu tài liệu và dữ liệu công ty — câu hỏi phức tạp có thể mất vài chục giây.
                  </p>
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Ô nhập */}
        <div className="p-3 sm:p-4 border-t border-slate-200 dark:border-slate-800 shrink-0">
          <form onSubmit={handleSendMessage} className="max-w-3xl mx-auto space-y-2">
            {/* File đang đính kèm — hiện ngay trên ô gõ như Claude/ChatGPT */}
            {attachments.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {attachments.map((a, idx) => (
                  <span
                    key={`${a.filename}-${idx}`}
                    className="inline-flex items-center gap-1.5 bg-blue-50 dark:bg-blue-950/50 border border-blue-200 dark:border-blue-900 text-blue-900 dark:text-blue-200 text-[11px] font-medium px-2 py-1 rounded-lg max-w-full"
                  >
                    {a.status === 'uploading' ? (
                      <Loader2 className="w-3 h-3 shrink-0 animate-spin" />
                    ) : (
                      <FileText className="w-3 h-3 shrink-0" />
                    )}
                    <span className="truncate">{a.filename}</span>
                    {a.status === 'uploading' && (
                      <span className="text-blue-500/80 dark:text-blue-300/70 shrink-0">
                        đang đọc…{' '}
                        {a.startedAt
                          ? `${Math.max(0, Math.round((Date.now() - a.startedAt) / 1000))}s`
                          : ''}
                      </span>
                    )}
                    {a.status === 'warning' && (
                      <AlertTriangle
                        className="w-3 h-3 text-amber-500 shrink-0"
                        aria-label="Bản scan — đọc có cảnh báo"
                      />
                    )}
                    {a.textChars > 0 && (
                      <span className="text-blue-500/80 dark:text-blue-300/70 tabular-nums shrink-0">
                        {a.textChars.toLocaleString('vi-VN')} ký tự
                      </span>
                    )}
                    {a.status !== 'uploading' && (
                      <button
                        type="button"
                        onClick={() => void removeAttachment(a)}
                        className="hover:text-red-600"
                        aria-label={`Bỏ ${a.filename}`}
                      >
                        <X className="w-3 h-3" />
                      </button>
                    )}
                  </span>
                ))}
              </div>
            )}

            {/* Máy chủ đã nói rõ đọc file gặp vấn đề gì — hiện nguyên văn, đừng
                nuốt. Người dùng đọc xong mới biết nên tin kết luận của AI tới
                đâu. */}
            {attachments.some((a) => a.warnings.length > 0) && (
              <div className="rounded-xl border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 p-2.5 space-y-1.5">
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
              </div>
            )}

            <div className="flex items-end gap-2 border border-slate-300 dark:border-slate-700 rounded-2xl p-2 shadow-sm bg-slate-50/60 dark:bg-slate-800/50 focus-within:border-hds-blue focus-within:ring-2 focus-within:ring-hds-blue/30 transition-colors">
              <textarea
                id="chat-input-textarea"
                ref={textareaRef}
                rows={2}
                value={inputQuestion}
                onChange={(e) => setInputQuestion(e.target.value)}
                onKeyDown={handleKeyDown}
                onPaste={handlePaste}
                disabled={isChatStreaming}
                placeholder="Nhập câu hỏi pháp lý… (Enter để gửi, Shift+Enter để xuống dòng)"
                aria-label="Câu hỏi gửi tới trợ lý AI"
                className="flex-1 px-2 py-1.5 bg-transparent text-sm text-slate-900 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none resize-none min-w-0"
              />

              <div className="flex items-center gap-1 shrink-0 pb-0.5">
                {!isClient && (
                  <>
                    <button
                      type="button"
                      onClick={() => fileInputRef.current?.click()}
                      disabled={!canUpload || uploading}
                      className="p-2 text-slate-400 hover:text-hds-navy dark:hover:text-blue-400 hover:bg-slate-200/70 dark:hover:bg-slate-700 rounded-xl transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent"
                      title="Đính kèm file cho bot đọc (kéo thả hoặc dán cũng được)"
                      aria-label="Đính kèm file"
                    >
                      {uploading ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <Paperclip className="w-4 h-4" />
                      )}
                    </button>
                    <input
                      ref={fileInputRef}
                      type="file"
                      multiple
                      accept={acceptExts}
                      className="hidden"
                      onChange={(e) => void handleAttach(e.target.files)}
                    />
                  </>
                )}

                {/* Đang trả lời thì chính chỗ này là nút DỪNG — không bắt
                    người dùng ngồi chờ hết một câu họ không cần nữa, và cũng
                    là lối thoát khi máy chạy quá lâu. */}
                {isChatStreaming ? (
                  <button
                    id="stop-chat-btn"
                    type="button"
                    onClick={handleStop}
                    className="p-2.5 rounded-xl transition-colors bg-hds-red text-white hover:bg-red-700"
                    title="Dừng câu trả lời đang chạy"
                    aria-label="Dừng câu trả lời"
                  >
                    <Square className="w-4 h-4 fill-current" />
                  </button>
                ) : (
                  <button
                    id="send-chat-btn"
                    type="submit"
                    disabled={!inputQuestion.trim() || uploading}
                    className="p-2.5 rounded-xl transition-colors bg-hds-navy text-hds-gold hover:bg-hds-navy-light disabled:bg-slate-200 dark:disabled:bg-slate-800 disabled:text-slate-400 disabled:cursor-not-allowed"
                    title="Gửi câu hỏi"
                    aria-label="Gửi câu hỏi"
                  >
                    <Send className="w-4 h-4" />
                  </button>
                )}
              </div>
            </div>

            <div className="flex items-center justify-between gap-3 text-[11px] text-slate-400 dark:text-slate-500 px-1">
              <span className="flex items-center gap-2 min-w-0">
                {/* Bộ chọn model — chỉ nhân viên nội bộ, khi máy chủ có model */}
                {!isClient && (genModels.length > 0 || cloudModels.length > 0) && (
                  <span className="flex items-center gap-1 shrink-0">
                    <Cpu className="w-3.5 h-3.5 text-hds-navy dark:text-blue-400" />
                    <select
                      value={selectedModel}
                      onChange={(e) => setSelectedModel(e.target.value)}
                      onFocus={refreshModels}
                      aria-label="Chọn mô hình AI"
                      title="Tự động: câu dữ liệu xác định không gọi model; tra cứu tài liệu dùng model chất lượng mặc định"
                      className="bg-transparent text-slate-500 dark:text-slate-400 font-semibold border border-slate-200 dark:border-slate-700 rounded-lg px-1.5 py-0.5 focus:ring-2 focus:ring-hds-blue focus:outline-none cursor-pointer max-w-[190px]"
                    >
                      <option value="auto">⚡ Tự động</option>
                      {/* Dấu ● = model đang nằm sẵn trong bộ nhớ, trả lời được
                          ngay. Dấu ○ = phải nạp vài GB từ ổ cứng trước đã. */}
                      {genModels.map((m) => (
                        <option key={m} value={m}>
                          {warmModels.includes(m) ? `● ${m}` : `○ ${m} (phải nạp)`}
                        </option>
                      ))}
                      {/* Model chạy ở nhà người ta: thông minh hơn nhưng TÍNH
                          TIỀN theo lượt hỏi, và dữ liệu rời khỏi máy chủ HDS.
                          Câu hỏi chạm hồ sơ khách/dữ liệu công ty ngoài phạm
                          vi admin cho phép sẽ tự động quay về model local. */}
                      {cloudModels.length > 0 && (
                        <optgroup label="Qua API — tính tiền theo lượt">
                          {cloudModels.map((m) => (
                            <option key={m} value={m}>
                              ☁ {m}
                            </option>
                          ))}
                        </optgroup>
                      )}
                    </select>
                  </span>
                )}
                <span className="flex items-center gap-1.5 min-w-0">
                  <span className="shrink-0">Chế độ:</span>
                  {attachments.length > 0 ? (
                    <span className="text-blue-700 dark:text-blue-300 font-semibold bg-blue-50 dark:bg-blue-950/60 px-1.5 py-0.5 rounded border border-blue-200 dark:border-blue-800 truncate">
                      Đọc {attachments.length} file đính kèm + kho nội bộ
                    </span>
                  ) : (
                    <span className="truncate">
                      {isClient ? 'Cổng khách hàng' : 'Tra cứu kho nội bộ'}
                    </span>
                  )}
                </span>
              </span>
              <span className="hidden sm:inline shrink-0">HDS Law Firm — Nền tảng AI Pháp lý</span>
            </div>
          </form>
        </div>
      </main>

      {showSourcePicker && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 backdrop-blur-sm p-4"
          onClick={() => setShowSourcePicker(false)}
          role="presentation"
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="source-picker-title"
            onClick={(event) => event.stopPropagation()}
            className="w-full max-w-2xl max-h-[82vh] flex flex-col bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-2xl overflow-hidden"
          >
            <div className="p-4 border-b border-slate-200 dark:border-slate-800 flex items-start justify-between gap-3">
              <div>
                <h3 id="source-picker-title" className="font-bold text-sm text-slate-900 dark:text-slate-100">
                  Chọn bộ nguồn cho hội thoại
                </h3>
                <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
                  Khi có lựa chọn, backend chỉ tra cứu trong các tài liệu này.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowSourcePicker(false)}
                className="p-1 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
                aria-label="Đóng bộ chọn nguồn"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-3 border-b border-slate-100 dark:border-slate-800">
              <div className="flex items-center gap-2 px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800">
                <Search className="w-4 h-4 text-slate-400" />
                <input
                  value={sourceQuery}
                  onChange={(event) => setSourceQuery(event.target.value)}
                  placeholder="Tìm theo tên tài liệu…"
                  className="flex-1 min-w-0 bg-transparent outline-none text-xs text-slate-800 dark:text-slate-100"
                />
              </div>
            </div>

            <div className="flex-1 overflow-y-auto p-3">
              {sourcesLoading ? (
                <div className="py-12 flex items-center justify-center gap-2 text-xs text-slate-500">
                  <Loader2 className="w-4 h-4 animate-spin" /> Đang tải kho tài liệu…
                </div>
              ) : visibleSourceDocs.length === 0 ? (
                <p className="py-12 text-center text-xs text-slate-500">
                  Không có tài liệu có quyền mở phù hợp.
                </p>
              ) : (
                <div className="space-y-1.5">
                  {visibleSourceDocs.map((doc) => {
                    const checked = selectedSourceIds.includes(doc.id);
                    return (
                      <label
                        key={doc.id}
                        className={`flex items-start gap-3 p-3 rounded-xl border cursor-pointer transition-colors ${
                          checked
                            ? 'bg-blue-50 dark:bg-blue-950/40 border-blue-300 dark:border-blue-800'
                            : 'bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800'
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() =>
                            setSelectedSourceIds((ids) =>
                              checked ? ids.filter((id) => id !== doc.id) : [...ids, doc.id]
                            )
                          }
                          className="sr-only"
                        />
                        <span
                          className={`mt-0.5 w-4 h-4 rounded border flex items-center justify-center shrink-0 ${
                            checked
                              ? 'bg-hds-navy border-hds-navy text-hds-gold'
                              : 'border-slate-300 dark:border-slate-600'
                          }`}
                        >
                          {checked && <Check className="w-3 h-3" />}
                        </span>
                        <span className="min-w-0">
                          <span className="block text-xs font-semibold text-slate-800 dark:text-slate-100 break-words">
                            {doc.title}
                          </span>
                          {(doc.doc_type || doc.department) && (
                            <span className="block mt-0.5 text-[10px] text-slate-500 dark:text-slate-400">
                              {[doc.doc_type, doc.department].filter(Boolean).join(' · ')}
                            </span>
                          )}
                        </span>
                      </label>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="p-3 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between gap-3">
              <button
                type="button"
                onClick={() => setSelectedSourceIds([])}
                disabled={selectedSourceIds.length === 0}
                className="px-3 py-2 text-xs font-semibold text-slate-500 hover:text-hds-red disabled:opacity-40"
              >
                Bỏ chọn tất cả
              </button>
              <button
                type="button"
                onClick={() => setShowSourcePicker(false)}
                className="px-4 py-2 rounded-xl bg-hds-navy text-hds-gold text-xs font-bold"
              >
                Dùng {selectedSourceIds.length || 'toàn bộ'} nguồn
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
