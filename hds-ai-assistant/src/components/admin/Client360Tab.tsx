import React, { useEffect, useState } from 'react';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import type { Client, Client360Data } from '../../types';
import { MATTER_STATUS_BADGES, DOC_TYPE_LABELS } from '../../constants';
import {
  Building2,
  History,
  AlertCircle,
  ShieldAlert,
  Lightbulb,
  Briefcase,
  FileText,
  RefreshCw,
  Save,
  Plus,
  Users2,
  CalendarClock,
  Loader2,
} from 'lucide-react';

const inputClass =
  'w-full px-3 py-2 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-xl focus:ring-2 focus:ring-hds-blue focus:outline-none transition-colors';

export const Client360Tab: React.FC = () => {
  const { showToast } = useApp();
  const [clients, setClients] = useState<Client[]>([]);
  const [selectedClientId, setSelectedClientId] = useState<string>('');
  const [data360, setData360] = useState<Client360Data | null>(null);
  const [isLoadingList, setIsLoadingList] = useState(true);
  const [isLoading360, setIsLoading360] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  // Ghi chú bổ sung (nối thêm) và hai trường ghi đè
  const [historyNote, setHistoryNote] = useState('');
  const [issuesNote, setIssuesNote] = useState('');
  const [warnings, setWarnings] = useState('');
  const [suggestions, setSuggestions] = useState('');

  const fetchClientsList = async () => {
    setIsLoadingList(true);
    try {
      const list = await api.getClients();
      setClients(list);
      if (list.length > 0) setSelectedClientId((prev) => prev || String(list[0].id));
    } catch (err: any) {
      showToast(err?.message || 'Lỗi khi tải danh sách khách hàng', 'error');
    } finally {
      setIsLoadingList(false);
    }
  };

  const fetch360Detail = async (id: string) => {
    if (!id) return;
    setIsLoading360(true);
    setDetailError(null);
    try {
      const res = await api.getClient360(Number(id));
      setData360(res);
      setHistoryNote('');
      setIssuesNote('');
      setWarnings(res.profile?.warnings || '');
      setSuggestions(res.profile?.suggestions || '');
    } catch (err: any) {
      const msg = err?.message || 'Lỗi khi tải hồ sơ khách hàng 360°';
      setDetailError(msg);
      setData360(null);
      showToast(msg, 'error');
    } finally {
      setIsLoading360(false);
    }
  };

  useEffect(() => {
    fetchClientsList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (selectedClientId) fetch360Detail(selectedClientId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedClientId]);

  const handleUpdateProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedClientId) return;

    if (!historyNote.trim() && !issuesNote.trim() && !warnings.trim() && !suggestions.trim()) {
      showToast('Chưa có nội dung nào để cập nhật.', 'error');
      return;
    }

    setIsSubmitting(true);
    try {
      await api.updateClientProfile(Number(selectedClientId), {
        history_note: historyNote.trim() || undefined,
        issues_note: issuesNote.trim() || undefined,
        warnings: warnings.trim() || undefined,
        suggestions: suggestions.trim() || undefined,
      });
      showToast('Đã cập nhật hồ sơ khách hàng 360°.', 'success');
      await fetch360Detail(selectedClientId);
    } catch (err: any) {
      showToast(err?.message || 'Lỗi khi cập nhật hồ sơ khách hàng', 'error');
    } finally {
      setIsSubmitting(false);
    }
  };

  const blocks = data360
    ? [
        {
          title: 'Lịch sử vụ việc và quan hệ hợp tác',
          icon: History,
          text: data360.profile?.history,
          empty: 'Chưa ghi nhận lịch sử tư vấn.',
          accent: 'text-hds-blue dark:text-blue-400',
          border: 'border-slate-200 dark:border-slate-800',
        },
        {
          title: 'Vấn đề pháp lý tồn đọng',
          icon: AlertCircle,
          text: data360.profile?.issues,
          empty: 'Chưa ghi nhận vướng mắc cần xử lý.',
          accent: 'text-amber-700 dark:text-amber-400',
          border: 'border-slate-200 dark:border-slate-800',
        },
        {
          title: 'Cảnh báo rủi ro và thời hiệu',
          icon: ShieldAlert,
          text: data360.profile?.warnings,
          empty: 'Hiện không có cảnh báo thời hiệu.',
          accent: 'text-hds-red dark:text-red-400',
          border: 'border-red-200 dark:border-red-900/50',
        },
        {
          title: 'Gợi ý phương án và chiến lược',
          icon: Lightbulb,
          text: data360.profile?.suggestions,
          empty: 'Chưa có gợi ý chiến lược bổ sung.',
          accent: 'text-hds-green dark:text-emerald-400',
          border: 'border-emerald-200 dark:border-emerald-900/50',
        },
      ]
    : [];

  return (
    <div className="space-y-6">
      {/* Tiêu đề và ô chọn khách hàng */}
      <div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-4 bg-white dark:bg-slate-900 p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
        <div>
          <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">
            Hồ sơ khách hàng 360°
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Tổng hợp lịch sử tư vấn, vấn đề tồn đọng, cảnh báo thời hiệu và gợi ý phương án pháp lý
          </p>
        </div>

        <div className="flex items-center gap-2 w-full lg:w-auto">
          <Building2 className="w-4 h-4 text-slate-400 shrink-0" />
          <select
            value={selectedClientId}
            onChange={(e) => setSelectedClientId(e.target.value)}
            disabled={isLoadingList || clients.length === 0}
            aria-label="Chọn khách hàng"
            className="px-3.5 py-2 border border-slate-300 dark:border-slate-700 rounded-xl bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-xs font-bold focus:ring-2 focus:ring-hds-blue focus:outline-none flex-1 lg:w-72 disabled:opacity-60 transition-colors"
          >
            {clients.length === 0 && <option value="">Không có khách hàng nào</option>}
            {clients.map((c) => (
              <option key={c.id} value={String(c.id)}>
                [{c.code}] {c.name}
              </option>
            ))}
          </select>
          <button
            onClick={() => fetch360Detail(selectedClientId)}
            disabled={!selectedClientId}
            className="p-2 bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 rounded-xl transition-colors shrink-0 disabled:opacity-50"
            title="Tải lại hồ sơ"
            aria-label="Tải lại hồ sơ"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading360 ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {isLoadingList && !data360 ? null : clients.length === 0 ? (
        <div className="bg-white dark:bg-slate-900 rounded-2xl p-12 text-center border border-slate-200 dark:border-slate-800 space-y-2">
          <Users2 className="w-10 h-10 text-slate-300 dark:text-slate-600 mx-auto" />
          <p className="font-semibold text-slate-700 dark:text-slate-300">
            Chưa có khách hàng nào bạn được phép xem
          </p>
          <p className="text-xs text-slate-500 dark:text-slate-400 max-w-md mx-auto">
            Ngoài Ban Quản trị, mỗi người chỉ thấy khách hàng thuộc phòng ban của mình.
          </p>
        </div>
      ) : isLoading360 ? (
        <div className="bg-white dark:bg-slate-900 rounded-2xl p-12 text-center text-slate-500 dark:text-slate-400 gap-2 text-sm flex items-center justify-center border border-slate-200 dark:border-slate-800">
          <RefreshCw className="w-5 h-5 animate-spin text-hds-navy dark:text-blue-400" />
          <span>Đang truy xuất hồ sơ 360°…</span>
        </div>
      ) : detailError ? (
        <div className="bg-white dark:bg-slate-900 rounded-2xl p-10 text-center border border-slate-200 dark:border-slate-800 space-y-3">
          <ShieldAlert className="w-10 h-10 text-hds-red mx-auto" />
          <h3 className="font-bold text-slate-800 dark:text-slate-100">Không mở được hồ sơ này</h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 max-w-md mx-auto">{detailError}</p>
        </div>
      ) : data360 ? (
        <div className="space-y-6">
          {/* Thẻ thông tin khách hàng */}
          <div className="bg-gradient-to-r from-hds-navy to-hds-blue text-white rounded-2xl p-6 shadow-md">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div className="space-y-1.5 min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="bg-hds-gold text-hds-navy font-black px-2 py-0.5 rounded text-[10px] uppercase tracking-wider">
                    {data360.client.code}
                  </span>
                  <span className="text-xs text-blue-200 font-mono">ID: {data360.client.id}</span>
                </div>
                <h3 className="text-xl font-extrabold break-words">{data360.client.name}</h3>
                <p className="text-xs text-blue-100 flex items-center gap-2">
                  <Building2 className="w-3.5 h-3.5 shrink-0" />
                  <span>{data360.client.department || 'Chưa gán phòng ban phụ trách'}</span>
                </p>
              </div>

              <div className="flex gap-3 text-xs bg-white/10 p-3 rounded-xl border border-white/15 shrink-0">
                <div className="text-center px-3">
                  <div className="text-2xl font-black">{data360.matters.length}</div>
                  <div className="text-[10px] text-blue-200 uppercase tracking-wide">Vụ việc</div>
                </div>
                <div className="w-px bg-white/20" />
                <div className="text-center px-3">
                  <div className="text-2xl font-black">{data360.documents.length}</div>
                  <div className="text-[10px] text-blue-200 uppercase tracking-wide">Tài liệu</div>
                </div>
              </div>
            </div>
          </div>

          {/* Bốn khối trí tuệ hồ sơ */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {blocks.map((block, idx) => {
              const Icon = block.icon;
              return (
                <div
                  key={block.title}
                  className={`bg-white dark:bg-slate-900 rounded-2xl border p-5 shadow-sm space-y-3 ${block.border}`}
                >
                  <div
                    className={`flex items-center gap-2 font-bold text-sm pb-2 border-b border-slate-100 dark:border-slate-800 ${block.accent}`}
                  >
                    <Icon className="w-4 h-4 shrink-0" />
                    <h4>
                      {idx + 1}. {block.title}
                    </h4>
                  </div>
                  <p
                    className={`text-xs whitespace-pre-line leading-relaxed min-h-[60px] ${
                      block.text
                        ? 'text-slate-700 dark:text-slate-300'
                        : 'text-slate-400 dark:text-slate-500 italic'
                    }`}
                  >
                    {block.text || block.empty}
                  </p>
                </div>
              );
            })}
          </div>

          {/* Danh sách vụ việc */}
          <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-5 shadow-sm space-y-4">
            <div className="flex items-center gap-2 border-b border-slate-100 dark:border-slate-800 pb-3">
              <Briefcase className="w-4 h-4 text-hds-navy dark:text-blue-400" />
              <h4 className="font-bold text-sm text-slate-900 dark:text-slate-100">
                Vụ việc liên quan ({data360.matters.length})
              </h4>
            </div>

            {data360.matters.length === 0 ? (
              <p className="text-xs text-slate-500 dark:text-slate-400 text-center py-4">
                Chưa có vụ việc nào được ghi nhận cho khách hàng này.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs min-w-[720px]">
                  <thead className="bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-300 font-bold uppercase tracking-wider">
                    <tr>
                      <th scope="col" className="p-3">Mã và tên vụ việc</th>
                      <th scope="col" className="p-3">Loại</th>
                      <th scope="col" className="p-3">Trạng thái</th>
                      <th scope="col" className="p-3">Hạn xử lý</th>
                      <th scope="col" className="p-3">Ngày mở</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                    {data360.matters.map((m) => {
                      const status = MATTER_STATUS_BADGES[m.status];
                      // Cảnh báo khi hạn xử lý đã qua mà vụ việc chưa hoàn thành
                      const isOverdue =
                        m.deadline && m.status !== 'hoan_thanh' && new Date(m.deadline) < new Date();

                      return (
                        <tr
                          key={m.id}
                          className="hover:bg-hds-soft/60 dark:hover:bg-slate-800/50 transition-colors"
                        >
                          <td className="p-3 font-semibold text-slate-900 dark:text-slate-100">
                            <div className="break-words">{m.title}</div>
                            {m.code && (
                              <span className="text-[10px] text-slate-400 dark:text-slate-500 font-mono">
                                {m.code}
                              </span>
                            )}
                          </td>
                          <td className="p-3 text-slate-600 dark:text-slate-400">
                            {m.type || m.matter_type || '—'}
                          </td>
                          <td className="p-3">
                            <span
                              className={`text-[10px] font-bold px-2 py-0.5 rounded-full border whitespace-nowrap ${
                                status?.badge ||
                                'bg-slate-100 text-slate-700 border-slate-300 dark:bg-slate-800 dark:text-slate-300'
                              }`}
                            >
                              {status?.label || m.status}
                            </span>
                          </td>
                          <td className="p-3 font-mono whitespace-nowrap">
                            {m.deadline ? (
                              <span
                                className={`inline-flex items-center gap-1 ${
                                  isOverdue
                                    ? 'text-hds-red dark:text-red-400 font-bold'
                                    : 'text-slate-500 dark:text-slate-400'
                                }`}
                                title={isOverdue ? 'Đã quá hạn xử lý' : undefined}
                              >
                                {isOverdue && <CalendarClock className="w-3 h-3" />}
                                {m.deadline}
                              </span>
                            ) : (
                              <span className="text-slate-400">—</span>
                            )}
                          </td>
                          <td className="p-3 text-slate-500 dark:text-slate-400 font-mono whitespace-nowrap">
                            {m.opened_at || '—'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Tài liệu của khách hàng */}
          <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-5 shadow-sm space-y-4">
            <div className="flex items-center gap-2 border-b border-slate-100 dark:border-slate-800 pb-3">
              <FileText className="w-4 h-4 text-hds-navy dark:text-blue-400" />
              <h4 className="font-bold text-sm text-slate-900 dark:text-slate-100">
                Kho văn bản và giấy tờ ({data360.documents.length})
              </h4>
            </div>

            {data360.documents.length === 0 ? (
              <p className="text-xs text-slate-500 dark:text-slate-400 text-center py-4">
                Chưa có tài liệu nào trong hồ sơ khách hàng này.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs min-w-[640px]">
                  <thead className="bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-300 font-bold uppercase tracking-wider">
                    <tr>
                      <th scope="col" className="p-3">Tên tài liệu</th>
                      <th scope="col" className="p-3">Loại</th>
                      <th scope="col" className="p-3">Tóm tắt</th>
                      <th scope="col" className="p-3">Ngày nạp</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                    {data360.documents.map((doc) => (
                      <tr
                        key={doc.id}
                        className="hover:bg-hds-soft/60 dark:hover:bg-slate-800/50 transition-colors"
                      >
                        <td className="p-3 font-semibold text-slate-900 dark:text-slate-100 break-words max-w-xs">
                          {doc.title}
                        </td>
                        <td className="p-3 text-slate-600 dark:text-slate-400 whitespace-nowrap">
                          {DOC_TYPE_LABELS[doc.doc_type] || doc.doc_type}
                        </td>
                        <td className="p-3 text-slate-600 dark:text-slate-400 max-w-sm leading-relaxed">
                          {doc.summary || '—'}
                        </td>
                        <td className="p-3 text-slate-500 dark:text-slate-400 font-mono whitespace-nowrap">
                          {doc.created_at}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Cập nhật hồ sơ */}
          <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-5 shadow-sm space-y-4">
            <div className="flex items-center gap-2 pb-2 border-b border-slate-100 dark:border-slate-800 text-slate-900 dark:text-slate-100 font-bold text-sm">
              <Plus className="w-4 h-4 text-hds-navy dark:text-blue-400" />
              <h4>Cập nhật hồ sơ 360°</h4>
            </div>

            <form onSubmit={handleUpdateProfile} className="space-y-4 text-xs">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label
                    htmlFor="history-note"
                    className="block font-semibold text-slate-700 dark:text-slate-300 mb-1"
                  >
                    Bổ sung lịch sử{' '}
                    <span className="font-normal text-slate-400">(nối thêm vào nội dung cũ)</span>
                  </label>
                  <input
                    id="history-note"
                    type="text"
                    value={historyNote}
                    onChange={(e) => setHistoryNote(e.target.value)}
                    placeholder="Sự kiện hợp tác mới…"
                    className={inputClass}
                  />
                </div>

                <div>
                  <label
                    htmlFor="issues-note"
                    className="block font-semibold text-slate-700 dark:text-slate-300 mb-1"
                  >
                    Bổ sung vấn đề{' '}
                    <span className="font-normal text-slate-400">(nối thêm vào nội dung cũ)</span>
                  </label>
                  <input
                    id="issues-note"
                    type="text"
                    value={issuesNote}
                    onChange={(e) => setIssuesNote(e.target.value)}
                    placeholder="Vướng mắc phát sinh mới…"
                    className={inputClass}
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label
                    htmlFor="warnings-field"
                    className="block font-semibold text-slate-700 dark:text-slate-300 mb-1"
                  >
                    Cảnh báo rủi ro{' '}
                    <span className="font-normal text-slate-400">(ghi đè toàn bộ)</span>
                  </label>
                  <textarea
                    id="warnings-field"
                    rows={3}
                    value={warnings}
                    onChange={(e) => setWarnings(e.target.value)}
                    placeholder="Mốc thời hiệu khởi kiện, rủi ro pháp lý…"
                    className={`${inputClass} resize-y`}
                  />
                </div>

                <div>
                  <label
                    htmlFor="suggestions-field"
                    className="block font-semibold text-slate-700 dark:text-slate-300 mb-1"
                  >
                    Gợi ý chiến lược{' '}
                    <span className="font-normal text-slate-400">(ghi đè toàn bộ)</span>
                  </label>
                  <textarea
                    id="suggestions-field"
                    rows={3}
                    value={suggestions}
                    onChange={(e) => setSuggestions(e.target.value)}
                    placeholder="Lộ trình đàm phán, phương án xử lý…"
                    className={`${inputClass} resize-y`}
                  />
                </div>
              </div>

              <div className="flex justify-end pt-2">
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-5 py-2.5 bg-hds-navy hover:bg-hds-navy-light text-white font-bold rounded-xl shadow-sm flex items-center gap-2 transition-colors disabled:bg-slate-300 dark:disabled:bg-slate-700 disabled:cursor-not-allowed"
                >
                  {isSubmitting ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      <span>Đang lưu…</span>
                    </>
                  ) : (
                    <>
                      <Save className="w-4 h-4" />
                      <span>Lưu hồ sơ</span>
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </div>
  );
};
