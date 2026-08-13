import React, { useEffect, useState } from 'react';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import type { LearnedDocument } from '../../types';
import { DOC_TYPES, DOC_TYPE_LABELS, ACCESS_LEVEL_BADGES, SOURCE_KIND_BADGES } from '../../constants';
import { BookOpen, Search, Filter, RefreshCw, Building2, Download } from 'lucide-react';
import { DriveSyncStatusCard } from './DriveSyncStatusCard';

export const LearnedDocsTab: React.FC = () => {
  const { showToast } = useApp();
  const [docs, setDocs] = useState<LearnedDocument[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [downloadingId, setDownloadingId] = useState<number | null>(null);

  const [searchQuery, setSearchQuery] = useState('');
  const [docTypeFilter, setDocTypeFilter] = useState('');

  const handleDownload = async (docId: number, title: string) => {
    setDownloadingId(docId);
    try {
      await api.downloadDocument(docId, title);
    } catch (err: any) {
      showToast(err?.message || 'Không tải được tệp gốc.', 'error');
    } finally {
      setDownloadingId(null);
    }
  };

  const fetchLearnedDocs = async (q = searchQuery, docType = docTypeFilter) => {
    setIsLoading(true);
    try {
      setDocs(await api.getDocuments({ q, doc_type: docType, limit: 200 }));
    } catch (err: any) {
      showToast(err?.message || 'Lỗi khi tải kho tài liệu đã học', 'error');
    } finally {
      setIsLoading(false);
    }
  };

  // Đổi bộ lọc thì tải lại luôn; ô tìm kiếm chờ người dùng bấm Tìm
  useEffect(() => {
    fetchLearnedDocs(searchQuery, docTypeFilter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docTypeFilter]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    fetchLearnedDocs();
  };

  return (
    <div className="space-y-6">
      {/* Tiêu đề khu vực */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 bg-white dark:bg-slate-900 p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
        <div>
          <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">
            Kho tri thức tài liệu đã học
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Toàn bộ văn bản đã được duyệt nhãn và nạp vào bộ nhớ trích dẫn của AI
          </p>
        </div>
        <button
          onClick={() => fetchLearnedDocs()}
          className="flex items-center gap-1.5 px-3.5 py-2 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 font-semibold text-xs rounded-xl transition-colors shrink-0"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Tải lại dữ liệu</span>
        </button>
      </div>

      {/* Trạng thái đồng bộ Drive — file nào đã học, file nào chờ xử lý và vì sao */}
      <DriveSyncStatusCard />

      {/* Tìm kiếm và lọc */}
      <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-4 shadow-sm flex flex-col md:flex-row items-stretch md:items-center gap-3 text-xs">
        <form onSubmit={handleSearchSubmit} className="flex-1 flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              type="search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Tìm theo tên tài liệu hoặc tóm tắt…"
              aria-label="Tìm kiếm tài liệu"
              className="w-full pl-9 pr-3 py-2 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-xl focus:ring-2 focus:ring-hds-blue focus:outline-none transition-colors"
            />
          </div>
          <button
            type="submit"
            className="px-4 py-2 bg-hds-navy hover:bg-hds-navy-light text-white font-bold rounded-xl shadow-sm shrink-0 transition-colors"
          >
            Tìm kiếm
          </button>
        </form>

        <div className="flex items-center gap-2 shrink-0">
          <Filter className="w-4 h-4 text-slate-400 shrink-0" />
          <select
            value={docTypeFilter}
            onChange={(e) => setDocTypeFilter(e.target.value)}
            aria-label="Lọc theo loại tài liệu"
            className="px-3 py-2 border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 dark:text-slate-100 rounded-xl font-medium focus:ring-2 focus:ring-hds-blue focus:outline-none w-full md:w-auto transition-colors"
          >
            <option value="">Tất cả loại tài liệu</option>
            {DOC_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Bảng tài liệu */}
      <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm overflow-hidden">
        {isLoading ? (
          <div className="p-12 text-center text-slate-500 dark:text-slate-400 gap-2 text-sm flex items-center justify-center">
            <RefreshCw className="w-5 h-5 animate-spin text-hds-navy dark:text-blue-400" />
            <span>Đang tìm kiếm trong kho tài liệu…</span>
          </div>
        ) : docs.length === 0 ? (
          <div className="p-12 text-center text-slate-500 dark:text-slate-400 space-y-2">
            <BookOpen className="w-10 h-10 text-slate-300 dark:text-slate-600 mx-auto" />
            <p className="font-semibold text-slate-700 dark:text-slate-300">
              Không tìm thấy tài liệu phù hợp
            </p>
            <p className="text-xs">Thử đổi từ khoá tìm kiếm hoặc bộ lọc loại tài liệu.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs min-w-[1020px]">
              <thead className="bg-slate-50 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 font-bold uppercase tracking-wider">
                <tr>
                  <th scope="col" className="p-4">Tên tài liệu</th>
                  <th scope="col" className="p-4">Loại</th>
                  <th scope="col" className="p-4">Nguồn</th>
                  <th scope="col" className="p-4">Tóm tắt</th>
                  <th scope="col" className="p-4">Mức truy cập</th>
                  <th scope="col" className="p-4 text-center">Số đoạn</th>
                  <th scope="col" className="p-4">Ngày nạp</th>
                  <th scope="col" className="p-4 text-right">Tải về</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {docs.map((doc) => {
                  const access = ACCESS_LEVEL_BADGES[doc.access_level];
                  const source = SOURCE_KIND_BADGES[doc.source_kind];

                  return (
                    <tr
                      key={doc.id}
                      className="hover:bg-hds-soft/60 dark:hover:bg-slate-800/50 transition-colors"
                    >
                      <td className="p-4 font-bold text-slate-900 dark:text-slate-100 max-w-xs">
                        <div className="space-y-1">
                          <span className="block leading-snug break-words">{doc.title}</span>
                          <span className="text-[10px] text-slate-400 dark:text-slate-500 font-mono block">
                            ID: {doc.id}
                          </span>
                          {doc.client_name && (
                            <span className="text-[10px] bg-purple-50 dark:bg-purple-950 text-purple-700 dark:text-purple-300 px-1.5 py-0.5 rounded font-semibold inline-flex items-center gap-1">
                              <Building2 className="w-3 h-3" />
                              {doc.client_name}
                            </span>
                          )}
                        </div>
                      </td>

                      <td className="p-4">
                        <span className="bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-200 px-2.5 py-1 rounded-lg border border-slate-200 dark:border-slate-700 font-semibold whitespace-nowrap">
                          {DOC_TYPE_LABELS[doc.doc_type] || doc.doc_type}
                        </span>
                      </td>

                      <td className="p-4">
                        <span
                          className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border whitespace-nowrap ${
                            source?.badge ||
                            'bg-slate-100 text-slate-700 border-slate-300 dark:bg-slate-800 dark:text-slate-300'
                          }`}
                        >
                          {source?.label || doc.source_kind}
                        </span>
                      </td>

                      <td className="p-4 text-slate-600 dark:text-slate-400 max-w-sm leading-relaxed">
                        {doc.summary}
                      </td>

                      <td className="p-4">
                        <span
                          className={`text-[10px] font-semibold px-2.5 py-1 rounded-full border whitespace-nowrap ${
                            access?.badge ||
                            'bg-slate-100 text-slate-700 border-slate-300 dark:bg-slate-800 dark:text-slate-300'
                          }`}
                        >
                          {access?.label || doc.access_level}
                        </span>
                      </td>

                      <td className="p-4 text-center">
                        <span className="bg-hds-soft dark:bg-slate-800 text-hds-navy dark:text-blue-300 font-bold px-2 py-1 rounded-lg border border-blue-100 dark:border-slate-700">
                          {doc.so_doan}
                        </span>
                      </td>

                      <td className="p-4 text-slate-500 dark:text-slate-400 font-mono whitespace-nowrap">
                        {doc.created_at}
                      </td>

                      <td className="p-4 text-right">
                        <button
                          onClick={() => handleDownload(doc.id, doc.title)}
                          disabled={downloadingId === doc.id}
                          className="inline-flex items-center gap-1 px-2.5 py-1 bg-hds-soft dark:bg-slate-800 text-hds-navy dark:text-blue-300 hover:bg-blue-100 dark:hover:bg-slate-700 font-bold rounded-lg border border-blue-200 dark:border-slate-700 text-[11px] disabled:opacity-50 transition-colors"
                          title="Tải bản gốc về máy"
                        >
                          {downloadingId === doc.id ? (
                            <RefreshCw className="w-3 h-3 animate-spin" />
                          ) : (
                            <Download className="w-3 h-3" />
                          )}
                          <span>Tải về</span>
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
