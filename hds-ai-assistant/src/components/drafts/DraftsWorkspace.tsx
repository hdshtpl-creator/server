import React, { useCallback, useEffect, useMemo, useState } from 'react';
import * as api from '../../api';
import { useApp } from '../../context/AppContext';
import type {
  BoMau,
  BrowseDocument,
  Client,
  DraftCheck,
  DraftCreateInput,
  DraftDocument,
  DraftTemplate,
  HoSoDaLuu,
  SoSanhKetQua,
  Source,
} from '../../types';
import { DOC_TYPES, DOC_TYPE_LABELS } from '../../constants';
import { DiffView } from '../common/DiffView';
import { DienBoMauPanel } from './DienBoMauPanel';
import { DienTheoBanCuPanel } from './DienTheoBanCuPanel';
import { HoSoDaLuuModal } from './HoSoDaLuuModal';
import {
  AlertTriangle,
  BookOpen,
  Check,
  CheckCircle2,
  Download,
  FilePenLine,
  FilePlus2,
  FolderClock,
  GitCompare,
  Package,
  ListChecks,
  Loader2,
  Plus,
  RefreshCw,
  ScanLine,
  Search,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Trash2,
  WandSparkles,
  X,
} from 'lucide-react';

/** Nhãn kết luận của kiểm tra mâu thuẫn pháp lý (app/kiem_tra_mau_thuan.py). */
const KET_LUAN_META: Record<string, { label: string; cls: string }> = {
  hop_le: { label: 'Hợp lệ', cls: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300' },
  canh_bao: { label: 'Cảnh báo', cls: 'bg-amber-100 text-amber-900 dark:bg-amber-950/50 dark:text-amber-300' },
  khong_ro: { label: 'Chưa rõ', cls: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300' },
};
const LOAI_MUC_LABEL: Record<string, string> = {
  lai_suat: 'Lãi suất', phat_vi_pham: 'Phạt vi phạm', thu_viec: 'Thử việc', luong_thu_viec: 'Lương thử việc',
  thoi_han_hop_dong: 'Thời hạn hợp đồng', gio_lam_viec_ngay: 'Giờ làm việc/ngày', gio_lam_viec_tuan: 'Giờ làm việc/tuần',
  lam_them_thang: 'Làm thêm/tháng', lam_them_nam: 'Làm thêm/năm', bao_truoc: 'Báo trước', dat_coc: 'Đặt cọc',
  so_tien: 'Số tiền', ty_le: 'Tỷ lệ', thoi_han: 'Thời hạn', ngay: 'Mốc ngày', cam_ket: 'Cam kết',
};

/** Khớp đúng dạng placeholder backend sinh ra (app/drafting.py PLACEHOLDER_RE). */
const PLACEHOLDER_PATTERN = /\[(?:CẦN BỔ SUNG|CAN BO SUNG)(?::\s*([^\]]*))?\]/gi;

const listPlaceholders = (content: string): { text: string; hint: string }[] => {
  const out: { text: string; hint: string }[] = [];
  const re = new RegExp(PLACEHOLDER_PATTERN.source, 'gi');
  let m: RegExpExecArray | null;
  while ((m = re.exec(content)) !== null) {
    out.push({ text: m[0], hint: (m[1] || '').trim() });
  }
  return out;
};

/** Thay lần lượt từng placeholder bằng giá trị người dùng điền; ô bỏ trống giữ nguyên. */
const fillPlaceholders = (content: string, values: string[]): string => {
  let index = -1;
  const re = new RegExp(PLACEHOLDER_PATTERN.source, 'gi');
  return content.replace(re, (match) => {
    index += 1;
    const value = (values[index] || '').trim();
    return value || match;
  });
};

const STATUS_META: Record<string, { label: string; cls: string }> = {
  draft: { label: 'Bản nháp', cls: 'bg-slate-100 text-slate-700 border-slate-300 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700' },
  generating: { label: 'Đang soạn', cls: 'bg-blue-100 text-blue-800 border-blue-300 dark:bg-blue-950 dark:text-blue-300 dark:border-blue-800' },
  generated: { label: 'Chờ duyệt', cls: 'bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-800' },
  needs_review: { label: 'Chờ duyệt', cls: 'bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-800' },
  approved: { label: 'Đã duyệt', cls: 'bg-emerald-100 text-emerald-800 border-emerald-300 dark:bg-emerald-950 dark:text-emerald-300 dark:border-emerald-800' },
  failed: { label: 'Lỗi', cls: 'bg-red-100 text-red-800 border-red-300 dark:bg-red-950 dark:text-red-300 dark:border-red-800' },
};

const getStatusMeta = (status?: string) =>
  STATUS_META[status || 'draft'] || {
    label: status || 'Bản nháp',
    cls: 'bg-slate-100 text-slate-700 border-slate-300 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700',
  };

const getContent = (draft: DraftDocument | null): string => {
  if (!draft) return '';
  if (draft.content_markdown) return draft.content_markdown;
  if (draft.content) return draft.content;
  if (draft.latest_version?.content_markdown) return draft.latest_version.content_markdown;
  const versions = Array.isArray(draft.versions) ? draft.versions : [];
  return [...versions].sort((a, b) => b.version_no - a.version_no)[0]?.content_markdown || '';
};

const getEvidence = (draft: DraftDocument | null): Source[] => {
  if (!draft) return [];
  if (Array.isArray(draft.sources)) return draft.sources;
  if (Array.isArray(draft.latest_version?.evidence)) {
    return draft.latest_version.evidence.map((item) => ({
      ...item,
      title: item.title || item.document_title || 'Tài liệu nguồn',
      quote: item.quote || item.excerpt || item.snippet,
    }));
  }
  const versions = Array.isArray(draft.versions) ? draft.versions : [];
  return [...versions].sort((a, b) => b.version_no - a.version_no)[0]?.evidence_snapshot || [];
};

const displayDate = (value?: string) => {
  if (!value) return '';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('vi-VN');
};

export const DraftsWorkspace: React.FC = () => {
  const { currentUser, showToast } = useApp();
  const [drafts, setDrafts] = useState<DraftDocument[]>([]);
  const [selected, setSelected] = useState<DraftDocument | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [documents, setDocuments] = useState<BrowseDocument[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [templates, setTemplates] = useState<DraftTemplate[]>([]);
  // BỘ MẪU HỒ SƠ (.docx tải lên ở Quản trị) đứng CÙNG danh sách "Mẫu soạn
  // thảo": nhân viên tải bộ lên rồi tìm nó ở đây (phản hồi 18/09/2026 "đã tải
  // bộ mẫu sao không có trong list?"). Chọn bộ là chuyển sang luồng ĐIỀN CẢ BỘ
  // — khác hẳn bản nháp một văn bản nên panel riêng, không trộn vào form.
  const [boMauList, setBoMauList] = useState<BoMau[]>([]);
  /** Bộ hồ sơ đã điền và ĐÃ LƯU của chính người này (giữ 7 ngày). */
  const [daLuuList, setDaLuuList] = useState<HoSoDaLuu[]>([]);
  const [moDaLuu, setMoDaLuu] = useState<string | null>(null);
  const [boMauChon, setBoMauChon] = useState<BoMau | null>(null);
  // Luồng "theo bộ hồ sơ khách cũ" (18/09/2026): không gắn với bộ mẫu nào,
  // không cần mã chỗ trống — AI đọc bộ cũ rồi thay thông tin chủ thể.
  const [theoBanCu, setTheoBanCu] = useState(false);
  const [sourceQuery, setSourceQuery] = useState('');
  const [showRevise, setShowRevise] = useState(false);
  const [revisionInstructions, setRevisionInstructions] = useState('');
  const [showApprove, setShowApprove] = useState(false);
  const [approvalNote, setApprovalNote] = useState('');
  const [allowPlaceholders, setAllowPlaceholders] = useState(false);
  const [confirmNeedsReview, setConfirmNeedsReview] = useState(false);
  const [autofillBusy, setAutofillBusy] = useState(false);
  const [fieldLabels, setFieldLabels] = useState<Record<string, string>>({});
  const [showFill, setShowFill] = useState(false);
  const [fillValues, setFillValues] = useState<string[]>([]);
  // Kiểm tra mâu thuẫn pháp lý chạy nền (kế hoạch ngày 9) + so sánh phiên bản (ngày 8).
  const [checks, setChecks] = useState<DraftCheck[]>([]);
  const [showAllCheckItems, setShowAllCheckItems] = useState(false);
  const [showCompare, setShowCompare] = useState(false);
  const [cmpTu, setCmpTu] = useState<number>(1);
  const [cmpDen, setCmpDen] = useState<number>(2);
  const [cmpResult, setCmpResult] = useState<SoSanhKetQua | null>(null);
  const [cmpBusy, setCmpBusy] = useState(false);

  const selectedId = selected?.id ?? null;
  const selectedVersion = selected?.current_version ?? 0;
  useEffect(() => {
    if (!selectedId) { setChecks([]); return; }
    let alive = true;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const rows = await api.getDraftChecks(selectedId);
        if (!alive) return;
        setChecks(rows);
        // Còn lượt đang chạy thì thăm dò tiếp mỗi 6 giây — model mất 1–3 phút.
        if (rows.some((c: DraftCheck) => c.status === 'running')) timer = window.setTimeout(tick, 6000);
      } catch {
        /* chưa migrate bảng draft_checks hoặc mất mạng: im lặng, thẻ hiện "chưa có" */
      }
    };
    void tick();
    return () => { alive = false; if (timer) window.clearTimeout(timer); };
  }, [selectedId, selectedVersion]);

  const runCheck = async () => {
    if (!selected) return;
    setBusy('check');
    try {
      const rows = await api.runDraftCheck(selected.id);
      setChecks(rows);
      showToast('Đã bắt đầu kiểm tra mâu thuẫn pháp lý (chạy nền, 1–3 phút).', 'info');
    } catch (err: any) {
      showToast(err?.message || 'Không khởi động được kiểm tra.', 'error');
    } finally {
      setBusy(null);
    }
  };

  const openCompare = () => {
    if (!selected || (selected.current_version || 0) < 2) return;
    const den = selected.current_version || 2;
    setCmpTu(den - 1);
    setCmpDen(den);
    setCmpResult(null);
    setShowCompare(true);
  };
  const runCompare = async (tu: number, den: number) => {
    if (!selected || tu === den) return;
    setCmpBusy(true);
    try {
      setCmpResult(await api.compareDraftVersions(selected.id, tu, den));
    } catch (err: any) {
      showToast(err?.message || 'Không so sánh được.', 'error');
    } finally {
      setCmpBusy(false);
    }
  };
  useEffect(() => {
    if (showCompare) void runCompare(cmpTu, cmpDen);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showCompare, cmpTu, cmpDen]);
  const [form, setForm] = useState<DraftCreateInput>({
    title: '',
    document_type: 'advisory',
    instructions: '',
    client_id: null,
    template_id: null,
    input_data: {},
    source_document_ids: [],
  });

  const canApprove = Boolean(
    currentUser &&
      (currentUser.role === 'admin' || currentUser.role === 'ban_qt' || currentUser.can_review)
  );
  const isBanQt = Boolean(
    currentUser && (currentUser.is_banqt || currentUser.role === 'admin' || currentUser.role === 'ban_qt')
  );

  /** Cùng luật với backend (DELETE /drafts): người tạo xoá bản của mình khi
   *  CHƯA duyệt; Ban quản trị xoá được mọi bản. Máy chủ vẫn kiểm lại — đây
   *  chỉ để không chìa nút cho người chắc chắn bị từ chối. */
  const canDelete = (draft: DraftDocument | null): boolean => {
    if (!draft || !currentUser) return false;
    if (isBanQt) return true;
    const own = draft.created_by == null || draft.created_by === currentUser.id;
    return own && draft.status !== 'approved';
  };

  const closeApprove = () => {
    setShowApprove(false);
    setApprovalNote('');
    setAllowPlaceholders(false);
    setConfirmNeedsReview(false);
  };

  const loadDrafts = useCallback(async (preserveId?: number) => {
    setLoading(true);
    setError(null);
    try {
      const rows = await api.listDrafts();
      const list = Array.isArray(rows) ? rows : [];
      setDrafts(list);
      const wantedId = preserveId ?? selected?.id;
      if (wantedId && !selected) {
        const found = list.find((item) => item.id === wantedId);
        if (found) setSelected(found);
      }
    } catch (err: any) {
      setError(err?.message || 'Không tải được danh sách bản nháp.');
    } finally {
      setLoading(false);
    }
  }, [selected?.id]);

  const loadDaLuu = useCallback(async () => {
    try {
      const res = await api.listHoSoDaLuu();
      setDaLuuList(Array.isArray(res?.items) ? res.items : []);
    } catch {
      // Không có hồ sơ đã lưu thì cột vẫn phải mở được — đừng chặn màn hình
      // vì một danh sách phụ.
      setDaLuuList([]);
    }
  }, []);

  useEffect(() => {
    loadDrafts();
    loadDaLuu();
    // Chỉ nạp một lần khi mở workspace.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openDraft = async (draft: DraftDocument) => {
    setSelected(draft);
    setError(null);
    try {
      const detail = await api.getDraft(draft.id);
      if (detail) setSelected(detail);
    } catch (err: any) {
      setError(err?.message || 'Không tải được nội dung bản nháp.');
    }
  };

  const openCreate = async () => {
    setShowCreate(true);
    setBoMauChon(null);
    setTheoBanCu(false);
    if (documents.length || clients.length || boMauList.length) return;
    try {
      const [docs, clientRows, templateRows, boMauRes] = await Promise.all([
        api.getBrowseDocuments(),
        api.getClients().catch(() => [] as Client[]),
        api.listDraftTemplates().catch(() => [] as DraftTemplate[]),
        api.listBoMau().catch(() => ({ items: [] as BoMau[] } as any)),
      ]);
      setDocuments((Array.isArray(docs) ? docs : []).filter((doc) => doc.can_open));
      setClients(Array.isArray(clientRows) ? clientRows : []);
      setTemplates(Array.isArray(templateRows) ? templateRows : []);
      setBoMauList(Array.isArray(boMauRes?.items) ? boMauRes.items : []);
    } catch (err: any) {
      setError(err?.message || 'Không tải được kho nguồn.');
    }
  };

  const dienLaiBo = async (boId: number) => {
    setMoDaLuu(null);
    await openCreate();
    const dangCo = boMauList.find((item) => item.id === boId);
    if (dangCo) {
      setBoMauChon(dangCo);
      return;
    }
    try {
      const res = await api.listBoMau();
      const items = Array.isArray(res?.items) ? res.items : [];
      setBoMauList(items);
      const bo = items.find((item: BoMau) => item.id === boId);
      if (bo) setBoMauChon(bo);
      else setError('Bộ mẫu gốc không còn — hãy chọn bộ khác trong danh sách.');
    } catch (err: any) {
      setError(err?.message || 'Không tải được danh sách bộ mẫu.');
    }
  };

  const createDraft = async (event: React.FormEvent) => {
    event.preventDefault();
    // Đang ở luồng điền bộ mẫu / theo bản cũ: Enter trong ô của panel không
    // được biến thành lệnh tạo bản nháp rỗng.
    if (boMauChon || theoBanCu) return;
    if (!form.title.trim() || busy) return;
    setBusy('create');
    setError(null);
    try {
      const created = await api.createDraft({
        ...form,
        title: form.title.trim(),
        instructions: form.instructions?.trim(),
      });
      const draftId = created.id ?? created.draft_id;
      setShowCreate(false);
      setForm({
        title: '',
        document_type: 'advisory',
        instructions: '',
        client_id: null,
        template_id: null,
        input_data: {},
        source_document_ids: [],
      });
      await loadDrafts(draftId);
      if (draftId) {
        const detail = await api.getDraft(draftId);
        setSelected(detail);
      }
      showToast('Đã tạo bản nháp. Hãy bấm "Sinh nội dung" khi đã chọn đủ nguồn.', 'success');
    } catch (err: any) {
      setError(err?.message || 'Không tạo được bản nháp.');
    } finally {
      setBusy(null);
    }
  };

  const generate = async () => {
    if (!selected || busy) return;
    setBusy('generate');
    setError(null);
    try {
      const result = await api.generateDraft(selected.id);
      const detail = result?.id ? result : await api.getDraft(selected.id);
      setSelected(detail);
      await loadDrafts(selected.id);
      showToast('Đã sinh bản nháp mới. Cần kiểm tra bằng chứng trước khi duyệt.', 'success');
    } catch (err: any) {
      setError(err?.message || 'Không sinh được nội dung.');
    } finally {
      setBusy(null);
    }
  };

  const approve = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selected || busy) return;
    setBusy('approve');
    setError(null);
    try {
      const result = await api.approveDraft(selected.id, {
        note: approvalNote.trim() || undefined,
        allow_placeholders: allowPlaceholders,
        confirm_needs_review: confirmNeedsReview,
      });
      const detail = result?.id ? result : await api.getDraft(selected.id);
      setSelected(detail);
      await loadDrafts(selected.id);
      closeApprove();
      showToast('Đã phê duyệt phiên bản hiện tại.', 'success');
    } catch (err: any) {
      setError(err?.message || 'Không phê duyệt được bản nháp.');
    } finally {
      setBusy(null);
    }
  };

  const revise = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selected || !revisionInstructions.trim() || busy) return;
    setBusy('revise');
    setError(null);
    try {
      const result = await api.reviseDraft(selected.id, {
        instructions: revisionInstructions.trim(),
        change_note: revisionInstructions.trim(),
      });
      setSelected(result);
      setShowRevise(false);
      setRevisionInstructions('');
      await loadDrafts(selected.id);
      showToast('Đã tạo phiên bản sửa để kiểm tra lại.', 'success');
    } catch (err: any) {
      setError(err?.message || 'Không tạo được phiên bản sửa.');
    } finally {
      setBusy(null);
    }
  };

  const removeDraft = async (draft: DraftDocument) => {
    if (busy) return;
    const message =
      draft.status === 'approved'
        ? `Xoá bản ĐÃ DUYỆT "${draft.title}"? Mọi phiên bản và ghi nhận phê duyệt sẽ mất, không khôi phục được.`
        : `Xoá bản nháp "${draft.title}"? Mọi phiên bản của nó sẽ mất, không khôi phục được.`;
    if (!window.confirm(message)) return;
    setBusy('delete');
    setError(null);
    try {
      await api.deleteDraft(draft.id);
      setDrafts((prev) => prev.filter((item) => item.id !== draft.id));
      if (selected?.id === draft.id) setSelected(null);
      showToast('Đã xoá bản nháp.', 'success');
    } catch (err: any) {
      setError(err?.message || 'Không xoá được bản nháp.');
    } finally {
      setBusy(null);
    }
  };

  const exportFile = async (format: 'docx' | 'pdf' = 'docx') => {
    if (!selected || busy) return;
    setBusy('export');
    try {
      await api.exportDraft(selected.id, `${selected.title}.${format}`, format);
      const ten = format.toUpperCase();
      showToast(
        selected.status === 'approved'
          ? `Đã xuất tệp ${ten}.`
          : `Đã xuất ${ten} bản nháp — bản này chưa được phê duyệt.`,
        'success'
      );
    } catch (err: any) {
      setError(err?.message || 'Không xuất được tệp.');
    } finally {
      setBusy(null);
    }
  };

  /** Tải MỘT hồ sơ (CCCD/sơ yếu/CV — PDF, ảnh, DOCX) để bóc thông tin điền sẵn. */
  const handleAutofillFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || autofillBusy) return;
    setAutofillBusy(true);
    try {
      const res = await api.autofillDraft(file);
      const fields = res?.fields || {};
      const keys = Object.keys(fields);
      if (!keys.length) {
        showToast('Không bóc được trường thông tin nào từ hồ sơ này.', 'error');
        return;
      }
      setForm((prev) => {
        const merged: Record<string, unknown> = { ...(prev.input_data || {}) };
        for (const [key, value] of Object.entries(fields)) {
          // Người dùng đã gõ tay thì giữ nguyên, chỉ điền ô còn trống.
          if (merged[key] == null || merged[key] === '') merged[key] = value;
        }
        return { ...prev, input_data: merged };
      });
      setFieldLabels((prev) => ({ ...prev, ...(res.field_labels || {}) }));
      const warn = (res.warnings || []).length
        ? ' Hồ sơ đọc bằng OCR — kiểm tra lại từng giá trị trước khi dùng.'
        : '';
      showToast(`Đã bóc ${keys.length} trường từ "${file.name}".${warn}`, 'success');
    } catch (err: any) {
      showToast(err?.message || 'Không bóc được thông tin từ hồ sơ.', 'error');
    } finally {
      setAutofillBusy(false);
    }
  };

  const submitFill = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selected || busy) return;
    const current = getContent(selected);
    const filledCount = fillValues.filter((value) => value.trim()).length;
    if (!filledCount) {
      setShowFill(false);
      return;
    }
    setBusy('fill');
    setError(null);
    try {
      const result = await api.reviseDraft(selected.id, {
        content_markdown: fillPlaceholders(current, fillValues),
        change_note: `Điền ${filledCount} chỗ trống`,
      });
      setSelected(result);
      setShowFill(false);
      setFillValues([]);
      await loadDrafts(selected.id);
      showToast(`Đã điền ${filledCount} chỗ trống và lưu thành phiên bản mới.`, 'success');
    } catch (err: any) {
      setError(err?.message || 'Không lưu được các chỗ đã điền.');
    } finally {
      setBusy(null);
    }
  };

  const filteredSources = useMemo(() => {
    const query = sourceQuery.trim().toLocaleLowerCase('vi-VN');
    return query
      ? documents.filter((doc) => doc.title.toLocaleLowerCase('vi-VN').includes(query))
      : documents;
  }, [documents, sourceQuery]);

  const content = getContent(selected);
  const evidence = getEvidence(selected);
  const statusMeta = getStatusMeta(selected?.status);
  // Backend cho xuất mọi phiên bản (header X-Draft-Status mang trạng thái);
  // đây là luồng "docx realtime để điền chỗ trống" — không bắt chờ phê duyệt.
  const canExport = Boolean(content);
  const canGenerate = Boolean(selected && selected.status !== 'approved');
  const placeholders = useMemo(() => listPlaceholders(content), [content]);
  const latestGrounding = selected?.latest_version?.grounding_status || selected?.grounding_status;
  const latestPlaceholders = selected?.latest_version?.placeholder_count ?? selected?.placeholder_count ?? 0;
  const selectedTemplate = templates.find((item) => item.id === form.template_id);
  const requiredFields = Array.isArray(selectedTemplate?.required_fields)
    ? selectedTemplate.required_fields
    : [];

  return (
    <div className="flex-1 min-h-0 bg-hds-soft dark:bg-slate-950 p-3 sm:p-5">
      <div className="max-w-[1600px] mx-auto h-[calc(100dvh-6.5rem)] min-h-[560px] grid lg:grid-cols-[320px_minmax(0,1fr)] gap-4">
        <aside className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-sm flex flex-col min-h-0 overflow-hidden">
          <div className="p-4 border-b border-slate-200 dark:border-slate-800">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="font-bold text-sm text-slate-900 dark:text-slate-100">Bản nháp</h2>
                <p className="text-[10px] text-slate-500 dark:text-slate-400 mt-0.5">
                  {drafts.length} tài liệu
                </p>
              </div>
              <div className="flex gap-1">
                <button
                  type="button"
                  onClick={() => loadDrafts()}
                  disabled={loading}
                  className="p-2 rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
                  title="Làm mới"
                >
                  <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                </button>
                <button
                  type="button"
                  onClick={openCreate}
                  className="p-2 rounded-lg bg-hds-navy text-hds-gold hover:bg-hds-navy-light"
                  title="Tạo bản nháp"
                >
                  <Plus className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-2">
            {loading && drafts.length === 0 ? (
              <div className="py-12 flex items-center justify-center gap-2 text-xs text-slate-500">
                <Loader2 className="w-4 h-4 animate-spin" /> Đang tải…
              </div>
            ) : drafts.length === 0 ? (
              <button
                type="button"
                onClick={openCreate}
                className="w-full py-12 px-5 text-center rounded-xl border border-dashed border-slate-300 dark:border-slate-700 text-slate-500 hover:border-hds-blue"
              >
                <FilePlus2 className="w-8 h-8 mx-auto mb-2 opacity-50" />
                <span className="block text-xs font-semibold">Tạo bản nháp đầu tiên</span>
              </button>
            ) : (
              <div className="space-y-1">
                {drafts.map((draft) => {
                  const meta = getStatusMeta(draft.status);
                  return (
                    <div
                      key={draft.id}
                      className={`flex items-stretch gap-1 rounded-xl border transition-colors ${
                        selected?.id === draft.id
                          ? 'bg-blue-50 dark:bg-blue-950/40 border-blue-300 dark:border-blue-800'
                          : 'bg-white dark:bg-slate-900 border-transparent hover:bg-slate-50 dark:hover:bg-slate-800'
                      }`}
                    >
                      <button
                        type="button"
                        onClick={() => openDraft(draft)}
                        className="flex-1 min-w-0 text-left p-3"
                      >
                        <span className="block text-xs font-bold text-slate-800 dark:text-slate-100 line-clamp-2">
                          {draft.title}
                        </span>
                        <span className="mt-2 flex items-center justify-between gap-2">
                          <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded border ${meta.cls}`}>
                            {meta.label}
                          </span>
                          <span className="text-[9px] text-slate-400">{displayDate(draft.updated_at)}</span>
                        </span>
                      </button>
                      {canDelete(draft) && (
                        <button
                          type="button"
                          onClick={() => void removeDraft(draft)}
                          disabled={Boolean(busy)}
                          className="shrink-0 self-start mt-2 mr-1.5 p-1.5 rounded-lg text-slate-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950/40 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                          title="Xoá bản nháp này (không khôi phục được)"
                          aria-label={`Xoá bản nháp ${draft.title}`}
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            {daLuuList.length > 0 && (
              <div className="mt-3 pt-3 border-t border-slate-200 dark:border-slate-800">
                <p className="px-1 pb-1.5 text-[10px] font-bold uppercase tracking-wide text-slate-400 flex items-center gap-1.5">
                  <FolderClock className="w-3.5 h-3.5" /> Bộ hồ sơ đã điền · giữ 7 ngày
                </p>
                <div className="space-y-1">
                  {daLuuList.map((ho) => (
                    <button
                      key={ho.ma}
                      type="button"
                      onClick={() => setMoDaLuu(ho.ma)}
                      className="w-full text-left p-3 rounded-xl border border-transparent hover:bg-slate-50 dark:hover:bg-slate-800"
                    >
                      <span className="block text-xs font-bold text-slate-800 dark:text-slate-100 line-clamp-2">
                        {ho.ten}
                      </span>
                      <span className="mt-1.5 flex items-center justify-between gap-2">
                        <span className="text-[9px] text-slate-500 flex items-center gap-1">
                          <Package className="w-3 h-3" />
                          {ho.so_file_con}/{ho.so_file} file
                          {ho.so_thieu > 0 && (
                            <span className="text-amber-700 dark:text-amber-300 font-bold">
                              · thiếu {ho.so_thieu} ô
                            </span>
                          )}
                        </span>
                        <span
                          className={`text-[9px] ${
                            ho.con_lai_ngay < 1 ? 'text-hds-red font-bold' : 'text-slate-400'
                          }`}
                        >
                          {ho.con_lai_ngay < 1
                            ? `còn ${Math.max(1, Math.round(ho.con_lai_ngay * 24))} giờ`
                            : `còn ${Math.floor(ho.con_lai_ngay)} ngày`}
                        </span>
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </aside>

        <main className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-sm min-h-0 overflow-hidden flex flex-col">
          {error && (
            <div className="px-4 py-3 bg-red-50 dark:bg-red-950/50 border-b border-red-200 dark:border-red-900 text-xs text-red-800 dark:text-red-200 flex items-start justify-between gap-3">
              <span className="flex items-start gap-2"><AlertTriangle className="w-4 h-4 shrink-0" />{error}</span>
              <button onClick={() => setError(null)} aria-label="Đóng"><X className="w-4 h-4" /></button>
            </div>
          )}

          {!selected ? (
            <div className="flex-1 flex flex-col items-center justify-center text-center p-8">
              <FilePenLine className="w-12 h-12 text-hds-navy dark:text-blue-400 opacity-30" />
              <h3 className="mt-3 font-bold text-slate-700 dark:text-slate-200">Soạn tài liệu có căn cứ</h3>
              <p className="mt-1 max-w-md text-xs leading-relaxed text-slate-500 dark:text-slate-400">
                Chọn tài liệu nguồn, sinh bản nháp, kiểm tra chỗ thiếu và bằng chứng rồi mới phê duyệt để xuất DOCX.
              </p>
              <button onClick={openCreate} className="mt-4 px-4 py-2 rounded-xl bg-hds-navy text-hds-gold text-xs font-bold flex items-center gap-2">
                <Plus className="w-4 h-4" /> Tạo bản nháp
              </button>
            </div>
          ) : (
            <>
              <div className="p-4 border-b border-slate-200 dark:border-slate-800 flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="font-bold text-base text-slate-900 dark:text-slate-100 break-words">{selected.title}</h2>
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${statusMeta.cls}`}>{statusMeta.label}</span>
                  </div>
                  <p className="mt-1 text-[10px] text-slate-500 dark:text-slate-400">
                    {DOC_TYPE_LABELS[selected.document_type || selected.draft_type || 'other'] || selected.document_type || selected.draft_type}
                    {selected.current_version ? ` · Phiên bản ${selected.current_version}` : ''}
                    {selected.client_name ? ` · ${selected.client_name}` : ''}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {canGenerate && (
                    <button onClick={generate} disabled={Boolean(busy)} className="px-3 py-2 rounded-xl bg-hds-navy text-hds-gold text-xs font-bold flex items-center gap-1.5 disabled:opacity-50">
                      {busy === 'generate' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                      Sinh nội dung
                    </button>
                  )}
                  {content && selected.status !== 'approved' && placeholders.length > 0 && (
                    <button
                      onClick={() => {
                        setFillValues(placeholders.map(() => ''));
                        setShowFill(true);
                      }}
                      disabled={Boolean(busy)}
                      className="px-3 py-2 rounded-xl border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 text-amber-900 dark:text-amber-300 text-xs font-bold flex items-center gap-1.5 disabled:opacity-50"
                    >
                      <ListChecks className="w-4 h-4" /> Điền chỗ trống ({placeholders.length})
                    </button>
                  )}
                  {content && selected.status !== 'approved' && (
                    <button
                      onClick={() => setShowRevise(true)}
                      disabled={Boolean(busy)}
                      className="px-3 py-2 rounded-xl border border-blue-300 dark:border-blue-800 bg-blue-50 dark:bg-blue-950/40 text-blue-800 dark:text-blue-300 text-xs font-bold flex items-center gap-1.5 disabled:opacity-50"
                    >
                      <WandSparkles className="w-4 h-4" /> Yêu cầu sửa
                    </button>
                  )}
                  {canApprove && content && selected.status !== 'approved' && (
                    <button onClick={() => setShowApprove(true)} disabled={Boolean(busy)} className="px-3 py-2 rounded-xl border border-emerald-300 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-300 text-xs font-bold flex items-center gap-1.5 disabled:opacity-50">
                      {busy === 'approve' ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShieldCheck className="w-4 h-4" />}
                      Phê duyệt
                    </button>
                  )}
                  <button onClick={() => void exportFile('docx')} disabled={!canExport || Boolean(busy)} title={canExport ? 'Tải DOCX (bản chưa duyệt vẫn tải được để điền tiếp)' : 'Chưa có nội dung để xuất'} className="px-3 py-2 rounded-xl border border-slate-300 dark:border-slate-700 text-xs font-bold flex items-center gap-1.5 disabled:opacity-40">
                    {busy === 'export' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
                    Tải DOCX
                  </button>
                  {/* PDF do LibreOffice trên máy chủ chuyển từ chính bản DOCX
                      nên bố cục giống hệt — dùng để gửi khách, không sửa được. */}
                  <button onClick={() => void exportFile('pdf')} disabled={!canExport || Boolean(busy)} title={canExport ? 'Tải PDF (bố cục giống bản DOCX, dùng để gửi đi)' : 'Chưa có nội dung để xuất'} className="px-3 py-2 rounded-xl border border-slate-300 dark:border-slate-700 text-xs font-bold flex items-center gap-1.5 disabled:opacity-40">
                    {busy === 'export' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
                    Tải PDF
                  </button>
                  <button
                    onClick={openCompare}
                    disabled={(selected.current_version || 0) < 2 || Boolean(busy)}
                    title={(selected.current_version || 0) < 2 ? 'Cần ít nhất 2 phiên bản để so sánh' : 'Tô sáng phần thêm / xoá / sửa giữa hai phiên bản; xuất Word có track changes'}
                    className="px-3 py-2 rounded-xl border border-slate-300 dark:border-slate-700 text-xs font-bold flex items-center gap-1.5 disabled:opacity-40"
                  >
                    <GitCompare className="w-4 h-4" /> So sánh phiên bản
                  </button>
                  {canDelete(selected) && (
                    <button
                      onClick={() => void removeDraft(selected)}
                      disabled={Boolean(busy)}
                      title="Xoá bản nháp này (không khôi phục được)"
                      className="px-3 py-2 rounded-xl border border-red-300 dark:border-red-800 text-red-700 dark:text-red-300 hover:bg-red-50 dark:hover:bg-red-950/40 text-xs font-bold flex items-center gap-1.5 disabled:opacity-40"
                    >
                      {busy === 'delete' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
                      Xoá
                    </button>
                  )}
                </div>
              </div>

              <div className="flex-1 min-h-0 overflow-y-auto p-4 sm:p-6 grid xl:grid-cols-[minmax(0,1fr)_300px] gap-5">
                <section className="min-w-0">
                  {content ? (
                    <article className="min-h-[520px] whitespace-pre-wrap break-words text-sm leading-7 text-slate-800 dark:text-slate-200 bg-slate-50/70 dark:bg-slate-950/40 border border-slate-200 dark:border-slate-800 rounded-xl p-5 sm:p-7">
                      {content}
                    </article>
                  ) : (
                    <div className="min-h-[420px] flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 dark:border-slate-700 text-center p-8">
                      <Sparkles className="w-9 h-9 text-hds-gold opacity-70" />
                      <p className="mt-3 text-sm font-bold text-slate-700 dark:text-slate-200">Chưa sinh nội dung</p>
                      <p className="mt-1 text-xs text-slate-500">AI sẽ chỉ dùng bộ nguồn đã gắn và đánh dấu [CẦN BỔ SUNG] khi thiếu dữ liệu.</p>
                    </div>
                  )}
                </section>

                <aside className="space-y-3">
                  <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800">
                    <h3 className="font-bold text-xs flex items-center gap-2"><CheckCircle2 className="w-4 h-4 text-emerald-600" /> Kiểm soát chất lượng</h3>
                    <div className="mt-3 space-y-2 text-[11px] text-slate-600 dark:text-slate-300">
                      <p>Grounding: <strong>{latestGrounding || 'Chưa kiểm tra'}</strong></p>
                      <p>Chỗ cần bổ sung: <strong>{latestPlaceholders || selected.missing_fields?.length || 0}</strong></p>
                      {selected.instructions && <p className="pt-2 border-t border-slate-100 dark:border-slate-800 whitespace-pre-wrap">Yêu cầu: {selected.instructions}</p>}
                    </div>
                  </div>

                  {(() => {
                    // Kiểm tra mâu thuẫn pháp lý — kết quả cho bản hiện tại (chạy nền sau mỗi lần lưu).
                    const cur = checks.find((c) => c.version_no === (selected.current_version || 0)) || checks[0];
                    const meta = cur?.ket_luan ? KET_LUAN_META[cur.ket_luan] : null;
                    const items = cur?.items || [];
                    const shown = showAllCheckItems ? items : items.filter((i) => i.ket_luan !== 'hop_le').slice(0, 6);
                    return (
                      <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800">
                        <h3 className="font-bold text-xs flex items-center gap-2"><ShieldAlert className="w-4 h-4 text-amber-600" /> Kiểm tra mâu thuẫn pháp lý</h3>
                        <div className="mt-2 text-[11px] text-slate-600 dark:text-slate-300 space-y-2">
                          {!content ? (
                            <p className="text-slate-500">Chạy sau khi có nội dung.</p>
                          ) : !cur ? (
                            <p className="text-slate-500">Chưa kiểm tra bản này.</p>
                          ) : cur.status === 'running' ? (
                            <p className="flex items-center gap-1.5 text-slate-500"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Đang trích cam kết, thời hạn, con số và đối chiếu luật… (1–3 phút)</p>
                          ) : cur.status === 'error' ? (
                            <p className="text-red-600">Lỗi: {cur.error || 'không rõ'}</p>
                          ) : (
                            <>
                              <p className="flex flex-wrap items-center gap-2">
                                <span className={`px-2 py-0.5 rounded-full font-bold ${meta?.cls || ''}`}>{meta?.label || cur.ket_luan}</span>
                                <span className="text-slate-500">{cur.so_canh_bao} cảnh báo / {cur.so_muc} mục · v{cur.version_no}{cur.phuong_phap ? ` · ${cur.phuong_phap === 'quy_tac' ? 'quy tắc' : 'quy tắc + AI'}` : ''}</span>
                              </p>
                              {shown.length > 0 && (
                                <ul className="space-y-1.5 max-h-[320px] overflow-y-auto">
                                  {shown.map((it, i) => {
                                    const m = KET_LUAN_META[it.ket_luan] || KET_LUAN_META.khong_ro;
                                    return (
                                      <li key={i} className="p-2 rounded-lg bg-slate-50 dark:bg-slate-800">
                                        <p className="flex flex-wrap items-center gap-1.5">
                                          <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${m.cls}`}>{m.label}</span>
                                          <span className="font-semibold">{LOAI_MUC_LABEL[it.loai] || it.loai}</span>
                                          {it.vi_tri && <span className="text-slate-400">· {it.vi_tri}</span>}
                                        </p>
                                        {it.trich && <p className="mt-1 italic text-slate-500 border-l-2 border-slate-300 pl-2 break-words">{it.trich}</p>}
                                        {it.ly_do && <p className="mt-1">{it.ly_do}</p>}
                                        {it.can_cu && <p className="mt-0.5 text-[10px] text-slate-500">Căn cứ: {it.can_cu}</p>}
                                      </li>
                                    );
                                  })}
                                </ul>
                              )}
                              {items.length > shown.length && (
                                <button type="button" onClick={() => setShowAllCheckItems(true)} className="text-hds-navy dark:text-blue-300 font-semibold hover:underline">
                                  Xem tất cả {items.length} mục (kể cả hợp lệ)
                                </button>
                              )}
                              {showAllCheckItems && items.length > 0 && (
                                <button type="button" onClick={() => setShowAllCheckItems(false)} className="text-slate-500 hover:underline">Thu gọn</button>
                              )}
                            </>
                          )}
                          {content && (
                            <button
                              type="button"
                              onClick={() => void runCheck()}
                              disabled={Boolean(busy) || cur?.status === 'running'}
                              className="mt-1 inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-amber-400 text-amber-800 dark:text-amber-300 font-bold text-[11px] disabled:opacity-50"
                            >
                              {busy === 'check' ? <Loader2 className="w-3 h-3 animate-spin" /> : <ShieldAlert className="w-3 h-3" />} Kiểm tra lại
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })()}

                  <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800">
                    <h3 className="font-bold text-xs flex items-center gap-2"><BookOpen className="w-4 h-4 text-hds-gold" /> Bằng chứng ({evidence.length})</h3>
                    {evidence.length ? (
                      <div className="mt-3 space-y-2 max-h-[420px] overflow-y-auto">
                        {evidence.map((source, index) => (
                          <div key={`${source.chunk_id ?? source.document_id ?? index}`} className="p-2.5 rounded-lg bg-slate-50 dark:bg-slate-800 text-[10px]">
                            <p className="font-bold text-slate-700 dark:text-slate-200">{source.title || source.document_title || 'Tài liệu nguồn'}</p>
                            {(source.page_number ?? source.page) != null && <p className="mt-0.5 text-slate-500">Trang {source.page_number ?? source.page}</p>}
                            {(source.quote ?? source.snippet) && <p className="mt-1.5 border-l-2 border-hds-gold pl-2 leading-relaxed text-slate-600 dark:text-slate-300">{source.quote ?? source.snippet}</p>}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="mt-2 text-[10px] leading-relaxed text-slate-500">
                        Chưa có snapshot bằng chứng. Không phê duyệt nếu tài liệu có kết luận chưa truy vết được.
                      </p>
                    )}
                  </div>
                </aside>
              </div>
            </>
          )}
        </main>
      </div>

      {showCompare && selected && (
        <div className="fixed inset-0 z-50 bg-slate-950/60 backdrop-blur-sm flex items-center justify-center p-4" onClick={() => setShowCompare(false)} role="presentation">
          <div onClick={(event) => event.stopPropagation()} className="w-full max-w-5xl max-h-[92vh] overflow-y-auto bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-2xl">
            <div className="p-5 border-b border-slate-200 dark:border-slate-800 flex flex-wrap items-center justify-between gap-3 sticky top-0 bg-white dark:bg-slate-900 rounded-t-2xl">
              <div className="min-w-0">
                <h3 className="font-bold text-sm flex items-center gap-2"><GitCompare className="w-4 h-4 text-hds-gold" /> So sánh phiên bản — {selected.title}</h3>
                <p className="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">Phần xoá gạch đỏ, phần thêm xanh; xuất Word có track changes để chấp nhận / từ chối từng chỗ.</p>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <select value={cmpTu} onChange={(e) => setCmpTu(Number(e.target.value))} className="px-2 py-1.5 rounded-lg border border-slate-300 dark:border-slate-700 dark:bg-slate-800">
                  {Array.from({ length: selected.current_version || 0 }, (_, i) => i + 1).map((v) => <option key={v} value={v}>v{v}</option>)}
                </select>
                <span className="text-slate-400">→</span>
                <select value={cmpDen} onChange={(e) => setCmpDen(Number(e.target.value))} className="px-2 py-1.5 rounded-lg border border-slate-300 dark:border-slate-700 dark:bg-slate-800">
                  {Array.from({ length: selected.current_version || 0 }, (_, i) => i + 1).map((v) => <option key={v} value={v}>v{v}</option>)}
                </select>
                <button
                  type="button"
                  disabled={!cmpResult}
                  onClick={() => api.exportDraftCompare(selected.id, cmpTu, cmpDen, `${selected.title}-so-sanh-v${cmpTu}-v${cmpDen}.docx`).catch((e: any) => showToast(e?.message || 'Không xuất được.', 'error'))}
                  className="px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-700 font-bold flex items-center gap-1.5 disabled:opacity-40"
                >
                  <Download className="w-3.5 h-3.5" /> Word (track changes)
                </button>
                <button type="button" onClick={() => setShowCompare(false)} aria-label="Đóng"><X className="w-5 h-5 text-slate-400" /></button>
              </div>
            </div>
            <div className="p-5">
              {cmpBusy ? (
                <div className="py-10 flex items-center justify-center gap-2 text-xs text-slate-500"><Loader2 className="w-4 h-4 animate-spin" /> Đang so sánh…</div>
              ) : cmpTu === cmpDen ? (
                <p className="text-xs text-slate-500">Chọn hai phiên bản khác nhau.</p>
              ) : cmpResult ? (
                <DiffView ketQua={cmpResult} labelCu={`Phiên bản ${cmpResult.tu}`} labelMoi={`Phiên bản ${cmpResult.den}`} />
              ) : null}
            </div>
          </div>
        </div>
      )}

      {showCreate && (
        <div className="fixed inset-0 z-50 bg-slate-950/60 backdrop-blur-sm flex items-center justify-center p-4" onClick={() => setShowCreate(false)} role="presentation">
          <form onSubmit={createDraft} onClick={(event) => event.stopPropagation()} className="w-full max-w-3xl max-h-[90vh] overflow-y-auto bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-2xl">
            <div className="p-5 border-b border-slate-200 dark:border-slate-800 flex items-start justify-between gap-3">
              <div>
                <h3 className="font-bold text-base">
                  {theoBanCu
                    ? 'Làm bộ hồ sơ theo bản của khách cũ'
                    : boMauChon
                    ? `Điền bộ hồ sơ «${boMauChon.ten}»`
                    : 'Tạo bản nháp'}
                </h3>
                <p className="text-[11px] text-slate-500 mt-0.5">
                  {theoBanCu
                    ? 'Không cần mã chỗ trống — AI đọc bộ cũ rồi thay thông tin sang khách mới.'
                    : boMauChon
                    ? 'Điền dữ liệu vào các file Word có sẵn của bộ, giữ nguyên định dạng gốc.'
                    : 'Nguồn đã chọn là phạm vi duy nhất AI được dùng.'}
                </p>
              </div>
              <button type="button" onClick={() => setShowCreate(false)} aria-label="Đóng"><X className="w-5 h-5 text-slate-400" /></button>
            </div>

            <div className="p-5 space-y-4">
              {/* Ô này LUÔN hiện: công ty chưa có mẫu phương pháp hay bộ mẫu
                  nào thì vẫn còn lối "làm theo bộ hồ sơ khách cũ". */}
              <label className="space-y-1 block">
                  <span className="text-xs font-bold text-slate-700 dark:text-slate-300">Mẫu soạn thảo</span>
                  <select
                    value={theoBanCu ? 'ban_cu' : boMauChon ? `bo:${boMauChon.id}` : form.template_id ?? ''}
                    onChange={(event) => {
                      const raw = event.target.value;
                      if (raw === 'ban_cu') {
                        setTheoBanCu(true);
                        setBoMauChon(null);
                        setForm((prev) => ({ ...prev, template_id: null, input_data: {} }));
                        return;
                      }
                      setTheoBanCu(false);
                      if (raw.startsWith('bo:')) {
                        // Bộ mẫu hồ sơ: đổi sang luồng ĐIỀN CẢ BỘ .docx, không
                        // phải sinh bản nháp — panel riêng bên dưới.
                        const bo = boMauList.find((item) => item.id === Number(raw.slice(3)));
                        setBoMauChon(bo || null);
                        setForm((prev) => ({ ...prev, template_id: null, input_data: {} }));
                        return;
                      }
                      setBoMauChon(null);
                      const templateId = raw ? Number(raw) : null;
                      const template = templates.find((item) => item.id === templateId);
                      setForm((prev) => ({
                        ...prev,
                        template_id: templateId,
                        document_type: template?.document_type || prev.document_type,
                        input_data: {},
                      }));
                    }}
                    className="w-full px-3 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 dark:bg-slate-800 text-xs"
                  >
                    <option value="">Không dùng mẫu</option>
                    {templates.length > 0 && (
                      <optgroup label="Mẫu phương pháp — AI soạn bản nháp có nguồn">
                        {templates.map((template) => (
                          <option key={template.id} value={template.id}>{template.name}</option>
                        ))}
                      </optgroup>
                    )}
                    {boMauList.length > 0 && (
                      <optgroup label="Bộ mẫu hồ sơ — điền dữ liệu vào cả bộ file Word">
                        {boMauList.map((bo) => (
                          <option key={`bo-${bo.id}`} value={`bo:${bo.id}`}>
                            {bo.ten} ({bo.so_file} file .docx)
                          </option>
                        ))}
                      </optgroup>
                    )}
                    <optgroup label="Chưa có mẫu đặt sẵn">
                      <option value="ban_cu">Làm theo bộ hồ sơ khách cũ (không cần mã chỗ trống)</option>
                    </optgroup>
                  </select>
                  {theoBanCu ? (
                    <p className="text-[10px] text-slate-500 dark:text-slate-400">
                      Tải lên bộ hồ sơ của một khách đã làm xong + thông tin khách mới; AI đọc hiểu
                      rồi thay thông tin chủ thể, giữ nguyên định dạng và điều khoản.
                    </p>
                  ) : boMauChon ? (
                    <p className="text-[10px] text-slate-500 dark:text-slate-400">
                      {boMauChon.mo_ta
                        ? `${boMauChon.mo_ta} — `
                        : ''}
                      Bộ mẫu là các file Word có sẵn: chọn bộ là chuyển sang luồng điền cả bộ, không
                      sinh bản nháp mới.
                    </p>
                  ) : (
                    selectedTemplate?.description && (
                      <p className="text-[10px] text-slate-500 dark:text-slate-400">{selectedTemplate.description}</p>
                    )
                )}
              </label>

              {boMauChon && (
                <DienBoMauPanel bo={boMauChon} onSaved={() => void loadDaLuu()} />
              )}

              {theoBanCu && <DienTheoBanCuPanel onSaved={() => void loadDaLuu()} />}

              {!boMauChon && !theoBanCu && (
              <>
              <div className="grid sm:grid-cols-2 gap-4">
                <label className="space-y-1">
                  <span className="text-xs font-bold text-slate-700 dark:text-slate-300">Tên tài liệu *</span>
                  <input required value={form.title} onChange={(event) => setForm((prev) => ({ ...prev, title: event.target.value }))} placeholder="Ví dụ: Thư tư vấn chấm dứt hợp đồng" className="w-full px-3 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 dark:bg-slate-800 text-xs outline-none focus:ring-2 focus:ring-hds-blue" />
                </label>
                <label className="space-y-1">
                  <span className="text-xs font-bold text-slate-700 dark:text-slate-300">Loại tài liệu</span>
                  <select value={form.document_type} onChange={(event) => setForm((prev) => ({ ...prev, document_type: event.target.value }))} className="w-full px-3 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 dark:bg-slate-800 text-xs">
                    {DOC_TYPES.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}
                  </select>
                </label>
              </div>

              {requiredFields.length > 0 && (
                <div className="p-3 rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50/60 dark:bg-amber-950/30">
                  <p className="text-xs font-bold text-amber-900 dark:text-amber-200 mb-2">Dữ liệu bắt buộc của mẫu</p>
                  <div className="grid sm:grid-cols-2 gap-3">
                    {requiredFields.map((field, index) => {
                      const spec = typeof field === 'string' ? { key: field, label: field } : field;
                      const key = spec.key || spec.name || `field_${index + 1}`;
                      const label = spec.label || spec.name || spec.key || `Trường ${index + 1}`;
                      return (
                        <label key={key} className="space-y-1">
                          <span className="text-[11px] font-semibold text-slate-700 dark:text-slate-300">
                            {label}{spec.required !== false ? ' *' : ''}
                          </span>
                          <input
                            required={spec.required !== false}
                            value={String(form.input_data?.[key] ?? '')}
                            onChange={(event) => setForm((prev) => ({
                              ...prev,
                              input_data: { ...(prev.input_data || {}), [key]: event.target.value },
                            }))}
                            placeholder={spec.placeholder || ''}
                            className="w-full px-3 py-2 rounded-lg border border-amber-200 dark:border-amber-800 dark:bg-slate-900 text-xs outline-none focus:ring-2 focus:ring-hds-blue"
                          />
                        </label>
                      );
                    })}
                  </div>
                </div>
              )}

              <div className="p-3 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/60 dark:bg-slate-800/40">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-xs font-bold text-slate-700 dark:text-slate-300 flex items-center gap-1.5">
                      <ScanLine className="w-4 h-4 text-hds-gold" /> Tự điền từ hồ sơ
                    </p>
                    <p className="mt-0.5 text-[10px] leading-relaxed text-slate-500 dark:text-slate-400">
                      Tải CCCD / sơ yếu lý lịch / CV (PDF, ảnh chụp, DOCX) — hệ thống bóc họ tên,
                      số CCCD, địa chỉ… điền sẵn; ô bạn đã gõ tay được giữ nguyên.
                    </p>
                  </div>
                  <input
                    type="file"
                    id="autofill-file-input"
                    className="sr-only"
                    accept=".pdf,.docx,.doc,.txt,.md,.jpg,.jpeg,.png,.webp,.tif,.tiff,.bmp"
                    onChange={handleAutofillFile}
                  />
                  <label
                    htmlFor="autofill-file-input"
                    className={`shrink-0 px-3 py-2 rounded-xl border text-[11px] font-bold cursor-pointer flex items-center gap-1.5 ${
                      autofillBusy
                        ? 'opacity-60 pointer-events-none border-slate-300 dark:border-slate-700'
                        : 'border-hds-navy text-hds-navy dark:text-blue-300 dark:border-blue-700 hover:bg-hds-soft dark:hover:bg-slate-800'
                    }`}
                  >
                    {autofillBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ScanLine className="w-3.5 h-3.5" />}
                    {autofillBusy ? 'Đang đọc…' : 'Chọn hồ sơ'}
                  </label>
                </div>
                {(() => {
                  const requiredKeys = new Set(
                    requiredFields.map((field, index) => {
                      const spec = typeof field === 'string' ? { key: field } : field;
                      return spec.key || spec.name || `field_${index + 1}`;
                    })
                  );
                  const extraEntries = Object.entries(form.input_data || {}).filter(
                    ([key]) => !requiredKeys.has(key)
                  );
                  if (!extraEntries.length) return null;
                  return (
                    <div className="mt-3 grid sm:grid-cols-2 gap-3">
                      {extraEntries.map(([key, value]) => (
                        <label key={key} className="space-y-1">
                          <span className="flex items-center justify-between text-[11px] font-semibold text-slate-700 dark:text-slate-300">
                            <span>{fieldLabels[key] || key}</span>
                            <button
                              type="button"
                              aria-label={`Bỏ trường ${fieldLabels[key] || key}`}
                              onClick={() =>
                                setForm((prev) => {
                                  const next = { ...(prev.input_data || {}) };
                                  delete next[key];
                                  return { ...prev, input_data: next };
                                })
                              }
                              className="text-slate-400 hover:text-hds-red"
                            >
                              <X className="w-3 h-3" />
                            </button>
                          </span>
                          <input
                            value={String(value ?? '')}
                            onChange={(event) =>
                              setForm((prev) => ({
                                ...prev,
                                input_data: { ...(prev.input_data || {}), [key]: event.target.value },
                              }))
                            }
                            className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 dark:bg-slate-900 text-xs outline-none focus:ring-2 focus:ring-hds-blue"
                          />
                        </label>
                      ))}
                    </div>
                  );
                })()}
              </div>

              <label className="space-y-1 block">
                <span className="text-xs font-bold text-slate-700 dark:text-slate-300">Khách hàng (nếu có)</span>
                <select value={form.client_id ?? ''} onChange={(event) => setForm((prev) => ({ ...prev, client_id: event.target.value ? Number(event.target.value) : null }))} className="w-full px-3 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 dark:bg-slate-800 text-xs">
                  <option value="">Không gắn khách hàng</option>
                  {clients.map((client) => <option key={client.id} value={client.id}>{client.name}</option>)}
                </select>
              </label>

              <label className="space-y-1 block">
                <span className="text-xs font-bold text-slate-700 dark:text-slate-300">Yêu cầu soạn thảo</span>
                <textarea rows={4} value={form.instructions || ''} onChange={(event) => setForm((prev) => ({ ...prev, instructions: event.target.value }))} placeholder="Mục đích, người nhận, giọng văn, các ý bắt buộc…" className="w-full px-3 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 dark:bg-slate-800 text-xs resize-y outline-none focus:ring-2 focus:ring-hds-blue" />
              </label>

              <div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-xs font-bold text-slate-700 dark:text-slate-300">Tài liệu nguồn ({form.source_document_ids?.length || 0})</span>
                  {Boolean(form.source_document_ids?.length) && <button type="button" onClick={() => setForm((prev) => ({ ...prev, source_document_ids: [] }))} className="text-[10px] text-hds-red font-semibold">Bỏ chọn</button>}
                </div>
                <div className="mt-2 flex items-center gap-2 px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800">
                  <Search className="w-4 h-4 text-slate-400" />
                  <input value={sourceQuery} onChange={(event) => setSourceQuery(event.target.value)} placeholder="Tìm nguồn…" className="flex-1 bg-transparent outline-none text-xs" />
                </div>
                <div className="mt-2 max-h-48 overflow-y-auto space-y-1 rounded-xl border border-slate-200 dark:border-slate-700 p-2">
                  {filteredSources.length ? filteredSources.map((doc) => {
                    const checked = form.source_document_ids?.includes(doc.id) || false;
                    return (
                      <label key={doc.id} className={`flex items-start gap-2 p-2 rounded-lg cursor-pointer ${checked ? 'bg-blue-50 dark:bg-blue-950/40' : 'hover:bg-slate-50 dark:hover:bg-slate-800'}`}>
                        <input type="checkbox" className="sr-only" checked={checked} onChange={() => setForm((prev) => ({ ...prev, source_document_ids: checked ? (prev.source_document_ids || []).filter((id) => id !== doc.id) : [...(prev.source_document_ids || []), doc.id] }))} />
                        <span className={`mt-0.5 w-4 h-4 rounded border flex items-center justify-center shrink-0 ${checked ? 'bg-hds-navy border-hds-navy text-hds-gold' : 'border-slate-300 dark:border-slate-600'}`}>{checked && <Check className="w-3 h-3" />}</span>
                        <span className="text-[11px] font-medium text-slate-700 dark:text-slate-200 break-words">{doc.title}</span>
                      </label>
                    );
                  }) : <p className="py-5 text-center text-[11px] text-slate-500">Không có nguồn phù hợp.</p>}
                </div>
              </div>
              </>
              )}
            </div>

            <div className="p-4 border-t border-slate-200 dark:border-slate-800 flex justify-end gap-2">
              <button type="button" onClick={() => setShowCreate(false)} className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800">
                {boMauChon || theoBanCu ? 'Đóng' : 'Huỷ'}
              </button>
              {!boMauChon && !theoBanCu && (
                <button type="submit" disabled={!form.title.trim() || busy === 'create'} className="px-4 py-2 rounded-xl bg-hds-navy text-hds-gold text-xs font-bold flex items-center gap-2 disabled:opacity-50">
                  {busy === 'create' ? <Loader2 className="w-4 h-4 animate-spin" /> : <FilePlus2 className="w-4 h-4" />}
                  Tạo bản nháp
                </button>
              )}
            </div>
          </form>
        </div>
      )}

      {moDaLuu && (
        <HoSoDaLuuModal
          ma={moDaLuu}
          coBoMau={boMauList.length > 0}
          onClose={() => setMoDaLuu(null)}
          onXoa={() => void loadDaLuu()}
          onDoiTen={() => void loadDaLuu()}
          onDienLai={(boId) => void dienLaiBo(boId)}
        />
      )}

      {showRevise && selected && (
        <div
          className="fixed inset-0 z-50 bg-slate-950/60 backdrop-blur-sm flex items-center justify-center p-4"
          onClick={() => setShowRevise(false)}
          role="presentation"
        >
          <form
            onSubmit={revise}
            onClick={(event) => event.stopPropagation()}
            className="w-full max-w-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-2xl p-5"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="font-bold text-sm">Tạo phiên bản sửa</h3>
                <p className="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">
                  Bản hiện tại được giữ nguyên để truy vết; hệ thống tạo một version mới.
                </p>
              </div>
              <button type="button" onClick={() => setShowRevise(false)} aria-label="Đóng">
                <X className="w-5 h-5 text-slate-400" />
              </button>
            </div>
            <textarea
              rows={6}
              autoFocus
              required
              value={revisionInstructions}
              onChange={(event) => setRevisionInstructions(event.target.value)}
              placeholder="Nói rõ phần cần sửa, dữ liệu cần bổ sung hoặc giọng văn mong muốn…"
              className="mt-4 w-full px-3 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 dark:bg-slate-800 text-xs resize-y outline-none focus:ring-2 focus:ring-hds-blue"
            />
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" onClick={() => setShowRevise(false)} className="px-4 py-2 text-xs font-semibold text-slate-500">
                Huỷ
              </button>
              <button type="submit" disabled={!revisionInstructions.trim() || busy === 'revise'} className="px-4 py-2 rounded-xl bg-hds-navy text-hds-gold text-xs font-bold flex items-center gap-2 disabled:opacity-50">
                {busy === 'revise' ? <Loader2 className="w-4 h-4 animate-spin" /> : <WandSparkles className="w-4 h-4" />}
                Tạo phiên bản
              </button>
            </div>
          </form>
        </div>
      )}

      {showFill && selected && (
        <div
          className="fixed inset-0 z-50 bg-slate-950/60 backdrop-blur-sm flex items-center justify-center p-4"
          onClick={() => setShowFill(false)}
          role="presentation"
        >
          <form
            onSubmit={submitFill}
            onClick={(event) => event.stopPropagation()}
            className="w-full max-w-2xl max-h-[90vh] overflow-y-auto bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-2xl p-5"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="font-bold text-sm flex items-center gap-2">
                  <ListChecks className="w-4 h-4 text-hds-gold" /> Điền chỗ trống ({placeholders.length})
                </h3>
                <p className="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">
                  Giá trị bạn điền thay thẳng vào bản nháp và lưu thành phiên bản mới.
                  Ô bỏ trống giữ nguyên dấu [CẦN BỔ SUNG] để điền sau.
                </p>
              </div>
              <button type="button" onClick={() => setShowFill(false)} aria-label="Đóng">
                <X className="w-5 h-5 text-slate-400" />
              </button>
            </div>

            <div className="mt-4 space-y-3">
              {placeholders.map((item, index) => (
                <label key={`${index}-${item.hint}`} className="block space-y-1">
                  <span className="text-[11px] font-semibold text-slate-700 dark:text-slate-300">
                    {index + 1}. {item.hint || 'Chỗ trống chưa ghi rõ cần gì'}
                  </span>
                  <input
                    value={fillValues[index] || ''}
                    autoFocus={index === 0}
                    onChange={(event) =>
                      setFillValues((prev) => {
                        const next = [...prev];
                        next[index] = event.target.value;
                        return next;
                      })
                    }
                    placeholder="Bỏ trống nếu chưa có thông tin"
                    className="w-full px-3 py-2.5 rounded-xl border border-amber-200 dark:border-amber-800 dark:bg-slate-800 text-xs outline-none focus:ring-2 focus:ring-hds-blue"
                  />
                </label>
              ))}
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <button type="button" onClick={() => setShowFill(false)} className="px-4 py-2 text-xs font-semibold text-slate-500">
                Huỷ
              </button>
              <button
                type="submit"
                disabled={busy === 'fill' || !fillValues.some((value) => value.trim())}
                className="px-4 py-2 rounded-xl bg-hds-navy text-hds-gold text-xs font-bold flex items-center gap-2 disabled:opacity-50"
              >
                {busy === 'fill' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                Điền và lưu phiên bản
              </button>
            </div>
          </form>
        </div>
      )}

      {showApprove && selected && (
        <div
          className="fixed inset-0 z-50 bg-slate-950/60 backdrop-blur-sm flex items-center justify-center p-4"
          onClick={closeApprove}
          role="presentation"
        >
          <form
            onSubmit={approve}
            onClick={(event) => event.stopPropagation()}
            className="w-full max-w-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-2xl p-5"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="font-bold text-sm">Phê duyệt phiên bản {selected.current_version}</h3>
                <p className="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">
                  Sau khi duyệt, bản này bị khoá và mới được xem là tài liệu hoàn tất.
                </p>
              </div>
              <button type="button" onClick={closeApprove} aria-label="Đóng">
                <X className="w-5 h-5 text-slate-400" />
              </button>
            </div>

            <div className="mt-4 space-y-3">
              {latestPlaceholders > 0 && (
                <label className="flex items-start gap-3 p-3 rounded-xl border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={allowPlaceholders}
                    onChange={(event) => setAllowPlaceholders(event.target.checked)}
                    className="mt-0.5 accent-[#1f3864]"
                  />
                  <span className="text-[11px] leading-relaxed text-amber-900 dark:text-amber-200">
                    Tôi xác nhận đã kiểm tra và chấp nhận <strong>{latestPlaceholders}</strong> chỗ [CẦN BỔ SUNG].
                  </span>
                </label>
              )}

              {latestGrounding !== 'grounded' && (
                <label className="flex items-start gap-3 p-3 rounded-xl border border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/40 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={confirmNeedsReview}
                    onChange={(event) => setConfirmNeedsReview(event.target.checked)}
                    className="mt-0.5 accent-[#1f3864]"
                  />
                  <span className="text-[11px] leading-relaxed text-red-900 dark:text-red-200">
                    Grounding hiện là <strong>{latestGrounding || 'chưa kiểm tra'}</strong>. Tôi đã tự đối chiếu bản gốc và chịu trách nhiệm phê duyệt.
                  </span>
                </label>
              )}

              <label className="space-y-1 block">
                <span className="text-xs font-bold text-slate-700 dark:text-slate-300">Ghi chú duyệt</span>
                <textarea
                  rows={3}
                  value={approvalNote}
                  onChange={(event) => setApprovalNote(event.target.value)}
                  placeholder="Nội dung đã kiểm tra hoặc giải thích ngoại lệ…"
                  className="w-full px-3 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 dark:bg-slate-800 text-xs resize-y outline-none focus:ring-2 focus:ring-hds-blue"
                />
              </label>
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <button type="button" onClick={closeApprove} className="px-4 py-2 text-xs font-semibold text-slate-500">Huỷ</button>
              <button
                type="submit"
                disabled={
                  busy === 'approve' ||
                  (latestPlaceholders > 0 && !allowPlaceholders) ||
                  (latestGrounding !== 'grounded' && !confirmNeedsReview)
                }
                className="px-4 py-2 rounded-xl bg-emerald-700 text-white text-xs font-bold flex items-center gap-2 disabled:opacity-40"
              >
                {busy === 'approve' ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShieldCheck className="w-4 h-4" />}
                Xác nhận phê duyệt
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
};
