import React, { useEffect, useState } from 'react';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import type { MethodTemplate } from '../../types';
import { Plus, Boxes, RefreshCw, CheckCircle2, ListOrdered, Loader2 } from 'lucide-react';

/** Backend lưu `steps` ở cột TEXT; chế độ giả lập có thể trả mảng. Chuẩn hoá cả hai. */
const toStepList = (steps: MethodTemplate['steps']): string[] => {
  const raw = Array.isArray(steps) ? steps : String(steps || '').split('\n');
  return raw.map((s) => s.trim()).filter(Boolean);
};

export const MethodTemplatesTab: React.FC = () => {
  const { showToast } = useApp();
  const [methods, setMethods] = useState<MethodTemplate[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const [caseType, setCaseType] = useState('');
  const [stepsText, setStepsText] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const fetchMethods = async () => {
    setIsLoading(true);
    try {
      const data = await api.getMethods();
      setMethods(Array.isArray(data) ? data : []);
    } catch (err: any) {
      showToast(err?.message || 'Lỗi khi tải danh sách mẫu phương pháp', 'error');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchMethods();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleCreateMethod = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!caseType.trim() || !stepsText.trim()) {
      showToast('Vui lòng nhập tên loại vụ việc và các bước thực hiện.', 'error');
      return;
    }

    setIsSubmitting(true);
    try {
      await api.createMethod({
        case_type: caseType.trim(),
        steps: stepsText.split('\n').map((s) => s.trim()).filter(Boolean),
      });

      showToast(`Đã thêm mẫu phương pháp cho "${caseType.trim()}".`, 'success');
      setCaseType('');
      setStepsText('');
      // POST /methods chỉ trả {ok, method_id} nên phải tải lại danh sách
      await fetchMethods();
    } catch (err: any) {
      showToast(err?.message || 'Lỗi khi tạo mẫu phương pháp', 'error');
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-12 text-slate-500 dark:text-slate-400 gap-2 text-sm">
        <RefreshCw className="w-5 h-5 animate-spin text-hds-navy dark:text-blue-400" />
        <span>Đang tải danh mục mẫu phương pháp…</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Tiêu đề khu vực */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 bg-white dark:bg-slate-900 p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
        <div>
          <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">
            Mẫu phương pháp phân tích pháp lý
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Dạy AI quy trình xử lý chuẩn cho từng dạng vụ việc, áp dụng khi bật "Mẫu phương pháp"
            trong hội thoại
          </p>
        </div>
        <button
          onClick={fetchMethods}
          className="flex items-center gap-1.5 px-3.5 py-2 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 font-semibold text-xs rounded-xl transition-colors shrink-0"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Cập nhật</span>
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Biểu mẫu thêm mới */}
        <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-5 shadow-sm space-y-4 lg:col-span-1 h-fit">
          <div className="flex items-center gap-2 pb-3 border-b border-slate-100 dark:border-slate-800">
            <span className="p-2 bg-amber-50 dark:bg-amber-950 text-amber-600 dark:text-amber-400 rounded-xl">
              <Plus className="w-5 h-5" />
            </span>
            <div>
              <h3 className="font-bold text-sm text-slate-900 dark:text-slate-100">
                Thêm mẫu phương pháp
              </h3>
              <p className="text-[11px] text-slate-500 dark:text-slate-400 font-mono">
                POST /methods
              </p>
            </div>
          </div>

          <form onSubmit={handleCreateMethod} className="space-y-3.5 text-xs">
            <div>
              <label
                htmlFor="method-case-type"
                className="block font-semibold text-slate-700 dark:text-slate-300 mb-1"
              >
                Tên loại vụ việc
              </label>
              <input
                id="method-case-type"
                type="text"
                value={caseType}
                onChange={(e) => setCaseType(e.target.value)}
                placeholder="Ví dụ: Rà soát hợp đồng M&A"
                className="w-full px-3 py-2 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-xl focus:ring-2 focus:ring-hds-blue focus:outline-none transition-colors"
              />
            </div>

            <div>
              <label
                htmlFor="method-steps"
                className="block font-semibold text-slate-700 dark:text-slate-300 mb-1"
              >
                Các bước thực hiện — mỗi dòng một bước
              </label>
              <textarea
                id="method-steps"
                rows={7}
                value={stepsText}
                onChange={(e) => setStepsText(e.target.value)}
                placeholder={
                  'Bước 1: Kiểm tra tư cách pháp lý các bên…\nBước 2: Rà soát danh mục nghĩa vụ…\nBước 3: Đánh giá điều khoản bồi thường…'
                }
                className="w-full p-3 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-xl focus:ring-2 focus:ring-hds-blue focus:outline-none leading-relaxed resize-y transition-colors"
              />
            </div>

            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full py-2.5 rounded-xl font-bold text-white shadow-sm flex items-center justify-center gap-2 bg-hds-navy hover:bg-hds-navy-light disabled:bg-slate-300 dark:disabled:bg-slate-700 disabled:cursor-not-allowed transition-colors"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Đang thêm…</span>
                </>
              ) : (
                <>
                  <Plus className="w-4 h-4 text-hds-gold" />
                  <span>Thêm mẫu phương pháp</span>
                </>
              )}
            </button>
          </form>
        </div>

        {/* Danh sách hiện có */}
        <div className="lg:col-span-2 space-y-4">
          <h3 className="font-bold text-sm text-slate-800 dark:text-slate-200 flex items-center gap-2">
            <Boxes className="w-4 h-4 text-hds-gold" />
            <span>Mẫu quy trình đang áp dụng ({methods.length})</span>
          </h3>

          {methods.length === 0 ? (
            <div className="bg-white dark:bg-slate-900 rounded-2xl p-8 text-center border border-slate-200 dark:border-slate-800 text-slate-500 dark:text-slate-400 text-sm">
              Chưa có mẫu phương pháp nào. Hãy thêm mẫu đầu tiên ở khung bên trái.
            </div>
          ) : (
            <div className="space-y-3.5">
              {methods.map((method) => {
                const steps = toStepList(method.steps);

                return (
                  <div
                    key={method.id}
                    className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-5 shadow-sm hover:border-slate-300 dark:hover:border-slate-700 transition-colors space-y-3"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2 border-b border-slate-100 dark:border-slate-800 pb-2.5">
                      <div className="flex items-center gap-2.5 min-w-0">
                        <span className="p-2 bg-amber-50 dark:bg-amber-950 text-amber-700 dark:text-amber-400 rounded-xl font-bold text-xs shrink-0">
                          #{method.id}
                        </span>
                        <h4 className="font-bold text-sm text-slate-900 dark:text-slate-100 break-words">
                          {method.case_type}
                        </h4>
                      </div>

                      {method.approved && (
                        <span className="bg-emerald-100 dark:bg-emerald-950 text-emerald-800 dark:text-emerald-300 border border-emerald-300 dark:border-emerald-800 text-[11px] font-semibold px-2.5 py-0.5 rounded-full flex items-center gap-1 shrink-0">
                          <CheckCircle2 className="w-3 h-3" />
                          Đã duyệt
                        </span>
                      )}
                    </div>

                    <div className="space-y-1.5">
                      <div className="text-[11px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider flex items-center gap-1">
                        <ListOrdered className="w-3.5 h-3.5" />
                        <span>Các bước quy trình</span>
                      </div>

                      <ol className="space-y-1 pl-1">
                        {steps.map((step, idx) => (
                          <li
                            key={idx}
                            className="text-xs text-slate-700 dark:text-slate-300 bg-slate-50 dark:bg-slate-800/60 p-2 rounded-lg border border-slate-100 dark:border-slate-700 leading-relaxed"
                          >
                            {step}
                          </li>
                        ))}
                      </ol>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
