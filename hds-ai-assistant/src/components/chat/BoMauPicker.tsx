import React, { useEffect, useMemo, useState } from 'react';
import * as api from '../../api';
import type { BoMau } from '../../types';
import {
  Layers,
  ChevronDown,
  ChevronUp,
  Search,
  Loader2,
  X,
  Files,
  CheckSquare,
  Square,
} from 'lucide-react';

/**
 * Nút "Bộ mẫu" dưới/trên khung chat: chọn một BỘ MẪU HỒ SƠ (nhóm .docx mẫu
 * tải lên từ Quản trị) để AI điền dữ liệu khách vào từng file của bộ trong
 * một lượt. Dùng chung cho tab Hội thoại AI và tab Kiểm tra pháp lý.
 *
 * selectedFileIds rỗng = điền CẢ bộ; người dùng bỏ tích vài file là chỉ điền
 * phần còn lại (backend nhận bo_mau_file_ids).
 */
interface Props {
  selected: BoMau | null;
  selectedFileIds: number[];
  onSelect: (bo: BoMau | null) => void;
  onFileIdsChange: (ids: number[]) => void;
  /** Bấm "Điền ngay" trên chip bộ đã chọn — cha quyết định gửi lượt thế nào. */
  onFillNow?: () => void;
  disabled?: boolean;
  /** Menu mở lên trên (khung chat ở đáy) hay xuống dưới (thanh công cụ ở đỉnh). */
  direction?: 'up' | 'down';
  /** Neo mép trái hay mép phải của nút — nút nằm sát mép phải màn hình thì neo
   *  phải, không thì bảng 520px tràn ra ngoài viewport. */
  align?: 'left' | 'right';
}

export const BoMauPicker: React.FC<Props> = ({
  selected,
  selectedFileIds,
  onSelect,
  onFileIdsChange,
  onFillNow,
  disabled,
  direction = 'up',
  align = 'left',
}) => {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<BoMau[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  const load = async () => {
    if (loading) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.listBoMau();
      setItems(res.items || []);
      setLoaded(true);
    } catch (err: any) {
      setError(err?.message || 'Không tải được danh sách bộ mẫu.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open && !loaded) void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (b) => b.ten.toLowerCase().includes(q) || (b.mo_ta || '').toLowerCase().includes(q)
    );
  }, [items, search]);

  // Bộ đã chọn nhưng danh sách vừa tải lại (bộ vừa được sửa ở Quản trị): lấy
  // bản mới nhất theo id để danh sách file khớp máy chủ.
  const current = selected ? items.find((b) => b.id === selected.id) || selected : null;
  const allChecked = selectedFileIds.length === 0;
  const isChecked = (fid: number) => allChecked || selectedFileIds.includes(fid);
  const toggleFile = (fid: number) => {
    if (!current) return;
    const all = current.files.map((f) => f.id);
    const cur = allChecked ? all : selectedFileIds;
    const next = cur.includes(fid) ? cur.filter((x) => x !== fid) : [...cur, fid];
    // Tích lại đủ cả bộ thì quay về "cả bộ" (mảng rỗng) cho gọn.
    onFileIdsChange(next.length === all.length ? [] : next);
  };
  const soFileChon = current
    ? allChecked
      ? current.files.length
      : current.files.filter((f) => selectedFileIds.includes(f.id)).length
    : 0;

  const panelPos =
    (direction === 'up' ? 'bottom-full mb-2 ' : 'top-full mt-2 ') +
    (align === 'right' ? 'right-0' : 'left-0');

  return (
    <div className="relative">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          disabled={disabled}
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-xs font-semibold transition-colors disabled:opacity-50 ${
            current
              ? 'bg-amber-50 dark:bg-amber-950/50 text-amber-900 dark:text-amber-200 border-amber-300 dark:border-amber-800'
              : 'bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-700'
          }`}
          aria-expanded={open}
          title="Chọn bộ mẫu hồ sơ — AI điền dữ liệu khách vào từng file .docx của bộ"
        >
          <Layers className="w-3.5 h-3.5" />
          {current ? (
            <span className="max-w-[220px] truncate">
              Bộ mẫu: {current.ten}
              {current.files.length > 0 && ` (${soFileChon}/${current.files.length} file)`}
            </span>
          ) : (
            <span className="hidden sm:inline">Bộ mẫu</span>
          )}
          {open ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
        </button>
        {current && onFillNow && (
          <button
            type="button"
            onClick={onFillNow}
            disabled={disabled || soFileChon === 0}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-hds-navy text-hds-gold text-xs font-bold hover:bg-hds-navy-light disabled:opacity-50 transition-colors"
            title="Điền dữ liệu (file đính kèm + những gì đã trao đổi trong chat) vào từng file của bộ"
          >
            <Files className="w-3.5 h-3.5" />
            Điền bộ này
          </button>
        )}
        {current && (
          <button
            type="button"
            onClick={() => {
              onSelect(null);
              onFileIdsChange([]);
              setOpen(false);
            }}
            disabled={disabled}
            className="inline-flex items-center gap-1 text-[11px] text-slate-500 hover:text-red-600 disabled:opacity-50"
            title="Bỏ chọn bộ mẫu"
          >
            <X className="w-3 h-3" /> Bỏ chọn
          </button>
        )}
      </div>

      {open && (
        <div
          className={`absolute ${panelPos} w-[92vw] sm:w-[520px] max-h-[70vh] overflow-y-auto bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl shadow-lg z-30 p-2 animate-fade-in`}
        >
          <div className="flex items-center gap-2 px-2 py-1.5 mb-1 bg-hds-soft dark:bg-slate-800 rounded-lg">
            <Search className="w-3.5 h-3.5 text-slate-400 shrink-0" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') e.preventDefault();
              }}
              placeholder="Tìm bộ mẫu theo tên…"
              className="flex-1 bg-transparent text-xs focus:outline-none dark:text-slate-100"
            />
            <button
              type="button"
              onClick={() => void load()}
              className="text-[10px] text-slate-500 hover:text-hds-navy"
              title="Tải lại danh sách"
            >
              Tải lại
            </button>
          </div>

          {loading && !loaded ? (
            <div className="flex items-center gap-2 p-3 text-xs text-slate-500">
              <Loader2 className="w-4 h-4 animate-spin" /> Đang nạp bộ mẫu…
            </div>
          ) : error ? (
            <p className="p-3 text-xs text-red-600">{error}</p>
          ) : filtered.length === 0 ? (
            <p className="p-3 text-xs text-slate-500">
              {items.length === 0
                ? 'Chưa có bộ mẫu nào. Người có quyền duyệt tạo bộ và tải file .docx ở Quản trị → Bộ mẫu hồ sơ.'
                : 'Không có bộ mẫu nào khớp.'}
            </p>
          ) : (
            <ul className="space-y-0.5">
              {filtered.map((b) => (
                <li key={b.id}>
                  <button
                    type="button"
                    onClick={() => {
                      onSelect(b);
                      onFileIdsChange([]);
                    }}
                    className={`w-full text-left px-2.5 py-2 rounded-lg text-xs transition-colors ${
                      current?.id === b.id
                        ? 'bg-hds-navy text-white'
                        : 'hover:bg-hds-soft dark:hover:bg-slate-800 text-slate-700 dark:text-slate-200'
                    }`}
                  >
                    <span className="font-semibold block truncate">{b.ten}</span>
                    <span className="flex items-center gap-2 text-[10px] opacity-70">
                      <span>{b.so_file} file .docx</span>
                      {b.department_id == null ? <span>· cả công ty</span> : <span>· theo phòng</span>}
                      {b.mo_ta && <span className="truncate">· {b.mo_ta}</span>}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}

          {current && current.files.length > 0 && (
            <div className="mt-2 border-t border-slate-200 dark:border-slate-700 pt-2">
              <div className="flex items-center justify-between px-2 pb-1">
                <span className="text-[11px] font-bold text-slate-600 dark:text-slate-300">
                  File trong bộ «{current.ten}» — bỏ tích file không cần điền
                </span>
                <button
                  type="button"
                  onClick={() => onFileIdsChange([])}
                  className="text-[10px] text-hds-navy dark:text-blue-300 hover:underline"
                >
                  Chọn cả bộ
                </button>
              </div>
              <ul className="space-y-0.5">
                {current.files.map((f) => (
                  <li key={f.id}>
                    <button
                      type="button"
                      onClick={() => toggleFile(f.id)}
                      className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs hover:bg-hds-soft dark:hover:bg-slate-800 text-slate-700 dark:text-slate-200"
                    >
                      {isChecked(f.id) ? (
                        <CheckSquare className="w-3.5 h-3.5 text-hds-navy dark:text-blue-300 shrink-0" />
                      ) : (
                        <Square className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                      )}
                      <span className="truncate flex-1 text-left">{f.ten_file}</span>
                      <span className="text-[10px] text-slate-400 shrink-0">
                        {f.so_placeholder > 0 ? `${f.so_placeholder} chỗ trống` : 'không có {{…}}'}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <p className="px-2 pt-2 text-[10px] text-slate-400 dark:text-slate-500">
            Trong câu chat gọi thẳng tên bộ cũng được: "tạo bộ hồ sơ theo bộ mẫu «tên bộ» cho khách …".
            Muốn điền bằng <b>tờ khai thông tin</b> (một bảng gõ tay cho cả bộ) thì mở tab{' '}
            <b>Soạn tài liệu → Tạo bản nháp</b> và chọn bộ ở ô "Mẫu soạn thảo".
          </p>
        </div>
      )}
    </div>
  );
};
