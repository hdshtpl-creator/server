import React, { useEffect, useState } from 'react';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import type { BrowseDocument } from '../../types';
import { DOC_TYPE_LABELS } from '../../constants';
import {
  Search,
  Lock,
  LockOpen,
  FileText,
  RefreshCw,
  Building,
  ShieldAlert,
  ExternalLink,
} from 'lucide-react';

export const BrowseDocsTab: React.FC = () => {
  const { showToast } = useApp();
  const [docs, setDocs] = useState<BrowseDocument[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [isLoading, setIsLoading] = useState(true);

  const fetchBrowseDocs = async () => {
    setIsLoading(true);
    try {
      setDocs(await api.getBrowseDocuments({ q: searchQuery }));
    } catch (err: any) {
      showToast(err?.message || 'Lỗi khi tra cứu danh mục tài liệu', 'error');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchBrowseDocs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    fetchBrowseDocs();
  };

  return (
    <div className="space-y-6">
      {/* Tiêu đề khu vực */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 bg-white dark:bg-slate-900 p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
        <div>
          <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">
            Tra cứu danh mục tài liệu
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Danh sách mở cho toàn bộ nhân viên nội bộ. Hồ sơ ngoài phòng ban của bạn sẽ tự động bị
            che tên và khoá mở.
          </p>
        </div>
        <button
          onClick={fetchBrowseDocs}
          className="flex items-center gap-1.5 px-3.5 py-2 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 font-semibold text-xs rounded-xl transition-colors shrink-0"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Làm mới</span>
        </button>
      </div>

      {/* Giải thích cơ chế che tên */}
      <div className="p-4 bg-amber-50 dark:bg-amber-950/40 border border-amber-300 dark:border-amber-800 rounded-2xl text-amber-900 dark:text-amber-200 text-xs flex items-start gap-3 shadow-sm">
        <ShieldAlert className="w-5 h-5 shrink-0 mt-0.5" />
        <div className="space-y-1">
          <p className="font-bold">Cơ chế bảo mật che tên</p>
          <p className="leading-relaxed">
            Tài liệu thuộc phòng ban khác sẽ hiển thị dưới dạng{' '}
            <code className="bg-amber-100 dark:bg-amber-900 px-1 py-0.5 rounded font-mono text-[11px]">
              [Loại - Phòng] 🔒 Tài khoản chưa có quyền xem
            </code>
            , đồng thời phần tóm tắt và nút mở tệp đều bị khoá. Quyết định này do backend đưa ra, giao
            diện không thể vượt qua.
          </p>
        </div>
      </div>

      {/* Ô tìm kiếm */}
      <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-4 shadow-sm">
        <form onSubmit={handleSearchSubmit} className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              type="search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Tìm tài liệu theo từ khoá…"
              aria-label="Tìm kiếm danh mục tài liệu"
              className="w-full pl-9 pr-3 py-2 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-xl focus:ring-2 focus:ring-hds-blue focus:outline-none text-xs transition-colors"
            />
          </div>
          <button
            type="submit"
            className="px-4 py-2 bg-hds-navy hover:bg-hds-navy-light text-white font-bold rounded-xl text-xs shadow-sm shrink-0 transition-colors"
          >
            Tìm kiếm
          </button>
        </form>
      </div>

      {/* Bảng danh mục */}
      <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm overflow-hidden">
        {isLoading ? (
          <div className="p-12 text-center text-slate-500 dark:text-slate-400 gap-2 text-sm flex items-center justify-center">
            <RefreshCw className="w-5 h-5 animate-spin text-hds-navy dark:text-blue-400" />
            <span>Đang kiểm tra phân quyền và tải danh mục…</span>
          </div>
        ) : docs.length === 0 ? (
          <div className="p-12 text-center text-slate-500 dark:text-slate-400 space-y-2">
            <FileText className="w-10 h-10 text-slate-300 dark:text-slate-600 mx-auto" />
            <p className="font-semibold text-slate-700 dark:text-slate-300">
              Không tìm thấy tài liệu phù hợp
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs min-w-[820px]">
              <thead className="bg-slate-50 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 font-bold uppercase tracking-wider">
                <tr>
                  <th scope="col" className="p-4">Tên tài liệu</th>
                  <th scope="col" className="p-4">Loại</th>
                  <th scope="col" className="p-4">Phòng ban quản lý</th>
                  <th scope="col" className="p-4">Trạng thái</th>
                  <th scope="col" className="p-4 text-right">Thao tác</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {docs.map((doc) => (
                  <tr
                    key={doc.id}
                    className="hover:bg-hds-soft/60 dark:hover:bg-slate-800/50 transition-colors"
                  >
                    <td className="p-4 max-w-md">
                      {doc.can_open ? (
                        <div className="flex items-start gap-2 text-slate-900 dark:text-slate-100">
                          <FileText className="w-4 h-4 text-hds-blue shrink-0 mt-0.5" />
                          <div className="min-w-0">
                            <span className="font-bold break-words">{doc.title}</span>
                            {doc.summary && (
                              <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5 leading-snug line-clamp-2">
                                {doc.summary}
                              </p>
                            )}
                          </div>
                        </div>
                      ) : (
                        <div className="flex items-start gap-2 text-slate-500 dark:text-slate-400">
                          <Lock className="w-4 h-4 text-hds-gold shrink-0 mt-0.5" />
                          <span className="bg-slate-100 dark:bg-slate-800 px-2 py-1 rounded border border-slate-200 dark:border-slate-700 font-mono text-[11px] break-words">
                            {doc.title}
                          </span>
                        </div>
                      )}
                    </td>

                    <td className="p-4 text-slate-700 dark:text-slate-300 whitespace-nowrap">
                      {DOC_TYPE_LABELS[doc.doc_type || ''] || doc.doc_type || '—'}
                    </td>

                    <td className="p-4">
                      <span className="inline-flex items-center gap-1 bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 px-2 py-0.5 rounded text-[11px] font-medium border border-slate-200 dark:border-slate-700 whitespace-nowrap">
                        <Building className="w-3 h-3 shrink-0" />
                        {doc.department || 'Chưa gán phòng'}
                      </span>
                    </td>

                    <td className="p-4">
                      {doc.can_open ? (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-emerald-100 dark:bg-emerald-950 text-emerald-800 dark:text-emerald-300 border border-emerald-300 dark:border-emerald-800 whitespace-nowrap">
                          <LockOpen className="w-3 h-3" />
                          Được mở xem
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-amber-100 dark:bg-amber-950 text-amber-800 dark:text-amber-300 border border-amber-300 dark:border-amber-800 whitespace-nowrap">
                          <Lock className="w-3 h-3" />
                          Khoá bảo mật
                        </span>
                      )}
                    </td>

                    <td className="p-4 text-right">
                      {doc.can_open ? (
                        <button
                          onClick={() => showToast(`Đang mở tài liệu: ${doc.title}`, 'info')}
                          className="px-3 py-1.5 bg-hds-navy hover:bg-hds-navy-light text-white font-bold rounded-lg text-xs inline-flex items-center gap-1 shadow-sm transition-colors"
                        >
                          <ExternalLink className="w-3 h-3" />
                          <span>Mở</span>
                        </button>
                      ) : (
                        <button
                          disabled
                          className="px-3 py-1.5 bg-slate-100 dark:bg-slate-800 text-slate-400 dark:text-slate-500 font-bold rounded-lg text-xs inline-flex items-center gap-1 border border-slate-200 dark:border-slate-700 cursor-not-allowed"
                          title="Bạn chưa có quyền truy cập tài liệu của phòng ban này"
                        >
                          <Lock className="w-3 h-3" />
                          <span>Khoá</span>
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
