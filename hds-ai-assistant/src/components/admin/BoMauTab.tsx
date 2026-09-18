import React, { useEffect, useRef, useState } from 'react';
import { useApp } from '../../context/AppContext';
import * as api from '../../api';
import type { BoMau, BoMauListResponse, Department } from '../../types';
import {
  Layers,
  Plus,
  RefreshCw,
  Upload,
  Trash2,
  Download,
  ChevronDown,
  ChevronUp,
  Loader2,
  FileText,
  Pencil,
  Check,
  Sparkles,
  X,
} from 'lucide-react';
import { DienBoMauPanel } from '../drafts/DienBoMauPanel';

/**
 * Quản trị → Bộ mẫu hồ sơ: tạo bộ, tải các file .docx mẫu vào bộ, xem chỗ
 * trống {{…}} đã quét, gỡ file/gỡ bộ. Bộ nằm NGOÀI kho tri thức (không học,
 * không duyệt nhãn) — chỉ để AI điền trong chat.
 */
export const BoMauTab: React.FC = () => {
  const { showToast } = useApp();
  const [data, setData] = useState<BoMauListResponse | null>(null);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [loading, setLoading] = useState(true);

  // Biểu mẫu tạo bộ
  const [ten, setTen] = useState('');
  const [moTa, setMoTa] = useState('');
  const [deptId, setDeptId] = useState<string>('');
  const [creating, setCreating] = useState(false);

  // Trạng thái từng bộ
  const [openId, setOpenId] = useState<number | null>(null);
  const [uploadingId, setUploadingId] = useState<number | null>(null);
  const [progress, setProgress] = useState(0);
  const [editId, setEditId] = useState<number | null>(null);
  const [editTen, setEditTen] = useState('');
  const [editMoTa, setEditMoTa] = useState('');
  const [editDept, setEditDept] = useState<string>('');
  // Bộ đang được ĐIỀN (tải tờ khai → điền → tải lên) — cùng panel với tab Soạn
  // tài liệu, để người vừa tải bộ lên dùng thử ngay tại chỗ.
  const [dienBo, setDienBo] = useState<BoMau | null>(null);
  const fileInputs = useRef<Record<number, HTMLInputElement | null>>({});

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [res, depts] = await Promise.all([
        api.listBoMau(),
        api.getDepartments().catch(() => [] as Department[]),
      ]);
      setData(res);
      setDepartments(Array.isArray(depts) ? depts : []);
    } catch (err: any) {
      showToast(err?.message || 'Không tải được danh sách bộ mẫu.', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const items = data?.items || [];
  const coQuyen = Boolean(data?.co_quyen_sua);
  const deptName = (id: number | null) =>
    id == null ? 'Cả công ty' : departments.find((d) => d.id === id)?.name || `Phòng #${id}`;

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!ten.trim()) {
      showToast('Nhập tên bộ mẫu trước đã.', 'error');
      return;
    }
    setCreating(true);
    try {
      const res = await api.createBoMau({
        ten: ten.trim(),
        mo_ta: moTa.trim() || undefined,
        department_id: deptId ? Number(deptId) : null,
      });
      showToast(`Đã tạo bộ «${ten.trim()}». Giờ tải các file .docx mẫu vào bộ.`, 'success');
      setTen('');
      setMoTa('');
      setDeptId('');
      await fetchAll();
      setOpenId(res.id);
    } catch (err: any) {
      showToast(err?.message || 'Không tạo được bộ mẫu.', 'error');
    } finally {
      setCreating(false);
    }
  };

  const handleUpload = async (bo: BoMau, files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploadingId(bo.id);
    setProgress(0);
    try {
      const res = await api.uploadBoMauFiles({ boId: bo.id, files, onProgress: setProgress });
      const ok = res.ket_qua.filter((k) => k.ok).length;
      const loi = res.ket_qua.filter((k) => !k.ok);
      if (ok) showToast(`Đã thêm ${ok} file vào bộ «${bo.ten}».`, 'success');
      loi.forEach((k) => showToast(`${k.ten_file}: ${k.loi}`, 'error'));
      await fetchAll();
    } catch (err: any) {
      showToast(err?.message || 'Tải file lên thất bại.', 'error');
    } finally {
      setUploadingId(null);
      const input = fileInputs.current[bo.id];
      if (input) input.value = '';
    }
  };

  const handleDeleteFile = async (bo: BoMau, fileId: number, tenFile: string) => {
    if (!window.confirm(`Gỡ «${tenFile}» khỏi bộ «${bo.ten}»?`)) return;
    try {
      await api.deleteBoMauFile(bo.id, fileId);
      await fetchAll();
    } catch (err: any) {
      showToast(err?.message || 'Không gỡ được file.', 'error');
    }
  };

  const handleDeleteSet = async (bo: BoMau) => {
    if (!window.confirm(`Xoá bộ «${bo.ten}» cùng ${bo.so_file} file mẫu? Không hoàn tác được.`)) return;
    try {
      await api.deleteBoMau(bo.id);
      showToast(`Đã xoá bộ «${bo.ten}».`, 'success');
      if (openId === bo.id) setOpenId(null);
      await fetchAll();
    } catch (err: any) {
      showToast(err?.message || 'Không xoá được bộ.', 'error');
    }
  };

  const startEdit = (bo: BoMau) => {
    setEditId(bo.id);
    setEditTen(bo.ten);
    setEditMoTa(bo.mo_ta || '');
    setEditDept(bo.department_id == null ? '' : String(bo.department_id));
  };

  const saveEdit = async (bo: BoMau) => {
    try {
      await api.updateBoMau(bo.id, {
        ten: editTen.trim() || undefined,
        mo_ta: editMoTa,
        department_id: editDept ? Number(editDept) : null,
        doi_pham_vi: true,
      });
      setEditId(null);
      showToast('Đã lưu.', 'success');
      await fetchAll();
    } catch (err: any) {
      showToast(err?.message || 'Không lưu được.', 'error');
    }
  };

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center p-12 text-slate-500 dark:text-slate-400 gap-2 text-sm">
        <RefreshCw className="w-5 h-5 animate-spin text-hds-navy dark:text-blue-400" />
        <span>Đang tải bộ mẫu hồ sơ…</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 bg-white dark:bg-slate-900 p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
        <div>
          <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
            <Layers className="w-5 h-5 text-hds-gold" />
            Bộ mẫu hồ sơ
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Nhóm các file Word (.docx) mẫu đi cùng nhau — hợp đồng, phụ lục, biên bản… Trong chat,
            chọn bộ (hoặc gọi tên bộ) là AI điền thông tin khách vào từng file. Đang có{' '}
            <b>{items.length}/{data?.max_bo ?? 100}</b> bộ.
          </p>
        </div>
        <button
          onClick={() => void fetchAll()}
          className="flex items-center gap-1.5 px-3.5 py-2 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 font-semibold text-xs rounded-xl transition-colors shrink-0"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Cập nhật</span>
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {coQuyen && (
          <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-5 shadow-sm space-y-4 lg:col-span-1 h-fit">
            <div className="flex items-center gap-2 pb-3 border-b border-slate-100 dark:border-slate-800">
              <span className="p-2 bg-amber-50 dark:bg-amber-950 text-amber-600 dark:text-amber-400 rounded-xl">
                <Plus className="w-5 h-5" />
              </span>
              <div>
                <h3 className="font-bold text-sm text-slate-900 dark:text-slate-100">Tạo bộ mẫu mới</h3>
                <p className="text-[11px] text-slate-500 dark:text-slate-400">
                  Tạo bộ trước, rồi tải các file .docx vào bộ.
                </p>
              </div>
            </div>
            <form onSubmit={handleCreate} className="space-y-3.5 text-xs">
              <div>
                <label htmlFor="bo-mau-ten" className="block font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  Tên bộ (dùng để gọi trong chat)
                </label>
                <input
                  id="bo-mau-ten"
                  type="text"
                  value={ten}
                  onChange={(e) => setTen(e.target.value)}
                  placeholder="Ví dụ: HĐ thuê nhà + phụ lục"
                  maxLength={120}
                  className="w-full px-3 py-2 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-xl focus:ring-2 focus:ring-hds-blue focus:outline-none"
                />
              </div>
              <div>
                <label htmlFor="bo-mau-mo-ta" className="block font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  Mô tả (tuỳ chọn)
                </label>
                <textarea
                  id="bo-mau-mo-ta"
                  value={moTa}
                  onChange={(e) => setMoTa(e.target.value)}
                  rows={2}
                  placeholder="Bộ này dùng cho trường hợp nào, gồm những giấy tờ gì"
                  className="w-full px-3 py-2 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-xl focus:ring-2 focus:ring-hds-blue focus:outline-none resize-none"
                />
              </div>
              <div>
                <label htmlFor="bo-mau-dept" className="block font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  Phạm vi dùng
                </label>
                <select
                  id="bo-mau-dept"
                  value={deptId}
                  onChange={(e) => setDeptId(e.target.value)}
                  className="w-full px-3 py-2 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-xl focus:ring-2 focus:ring-hds-blue focus:outline-none"
                >
                  <option value="">Cả công ty</option>
                  {departments.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))}
                </select>
              </div>
              <button
                type="submit"
                disabled={creating || items.length >= (data?.max_bo ?? 100)}
                className="w-full flex items-center justify-center gap-2 bg-hds-navy text-hds-gold font-bold py-2.5 rounded-xl hover:bg-hds-navy-light transition-colors disabled:opacity-50"
              >
                {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
                Tạo bộ
              </button>
              <p className="text-[11px] text-slate-500 dark:text-slate-400">
                Mẹo: trong file Word đặt chỗ trống dạng <code>{'{{Tên bên A}}'}</code>,{' '}
                <code>{'{{Mã số thuế}}'}</code>… AI sẽ điền đúng chỗ. Không có thì AI tự tìm chuỗi
                cần thay, dễ sót hơn.
              </p>
            </form>
          </div>
        )}

        <div className={`space-y-3 ${coQuyen ? 'lg:col-span-2' : 'lg:col-span-3'}`}>
          {items.length === 0 ? (
            <div className="bg-white dark:bg-slate-900 rounded-2xl border border-dashed border-slate-300 dark:border-slate-700 p-8 text-center text-sm text-slate-500 dark:text-slate-400">
              Chưa có bộ mẫu nào.{' '}
              {coQuyen
                ? 'Tạo bộ đầu tiên ở khung bên trái.'
                : 'Người có quyền duyệt tài liệu mới tạo được bộ mẫu.'}
            </div>
          ) : (
            items.map((bo) => {
              const isOpen = openId === bo.id;
              const isEditing = editId === bo.id;
              return (
                <div
                  key={bo.id}
                  className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm"
                >
                  <div className="flex items-start gap-3 p-4">
                    <button
                      type="button"
                      onClick={() => setOpenId(isOpen ? null : bo.id)}
                      className="flex-1 min-w-0 text-left"
                      aria-expanded={isOpen}
                    >
                      {isEditing ? (
                        <div className="space-y-2 text-xs" onClick={(e) => e.stopPropagation()}>
                          <input
                            value={editTen}
                            onChange={(e) => setEditTen(e.target.value)}
                            maxLength={120}
                            className="w-full px-2.5 py-1.5 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-lg"
                          />
                          <input
                            value={editMoTa}
                            onChange={(e) => setEditMoTa(e.target.value)}
                            placeholder="Mô tả"
                            className="w-full px-2.5 py-1.5 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-lg"
                          />
                          <select
                            value={editDept}
                            onChange={(e) => setEditDept(e.target.value)}
                            className="w-full px-2.5 py-1.5 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-lg"
                          >
                            <option value="">Cả công ty</option>
                            {departments.map((d) => (
                              <option key={d.id} value={d.id}>
                                {d.name}
                              </option>
                            ))}
                          </select>
                        </div>
                      ) : (
                        <>
                          <div className="font-bold text-sm text-slate-900 dark:text-slate-100 truncate">
                            {bo.ten}
                          </div>
                          <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
                            {bo.so_file} file .docx · {deptName(bo.department_id)}
                            {bo.mo_ta && <span> · {bo.mo_ta}</span>}
                          </div>
                        </>
                      )}
                    </button>
                    <div className="flex items-center gap-1 shrink-0">
                      {!isEditing && bo.so_file > 0 && (
                        <button
                          type="button"
                          onClick={() => setDienBo(bo)}
                          className="px-2.5 py-1.5 rounded-lg bg-hds-navy text-hds-gold text-[11px] font-bold flex items-center gap-1.5"
                          title="Tải tờ khai, điền rồi tải lên — máy điền vào từng file của bộ"
                        >
                          <Sparkles className="w-3.5 h-3.5" /> Điền bộ
                        </button>
                      )}
                      {coQuyen && (isEditing ? (
                        <>
                          <button
                            type="button"
                            onClick={() => void saveEdit(bo)}
                            className="p-1.5 rounded-lg text-emerald-700 hover:bg-emerald-50 dark:hover:bg-emerald-950"
                            title="Lưu"
                          >
                            <Check className="w-4 h-4" />
                          </button>
                          <button
                            type="button"
                            onClick={() => setEditId(null)}
                            className="p-1.5 rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
                            title="Huỷ"
                          >
                            <X className="w-4 h-4" />
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            type="button"
                            onClick={() => startEdit(bo)}
                            className="p-1.5 rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
                            title="Sửa tên / mô tả / phạm vi"
                          >
                            <Pencil className="w-4 h-4" />
                          </button>
                          <button
                            type="button"
                            onClick={() => void handleDeleteSet(bo)}
                            className="p-1.5 rounded-lg text-red-600 hover:bg-red-50 dark:hover:bg-red-950"
                            title="Xoá bộ"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </>
                      ))}
                      <button
                        type="button"
                        onClick={() => setOpenId(isOpen ? null : bo.id)}
                        className="p-1.5 rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
                        title={isOpen ? 'Thu gọn' : 'Xem file trong bộ'}
                      >
                        {isOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                      </button>
                    </div>
                  </div>

                  {isOpen && (
                    <div className="border-t border-slate-100 dark:border-slate-800 px-4 py-3 space-y-3">
                      {coQuyen && (
                        <div className="flex flex-wrap items-center gap-2">
                          <input
                            ref={(el) => {
                              fileInputs.current[bo.id] = el;
                            }}
                            type="file"
                            accept=".docx"
                            multiple
                            className="hidden"
                            onChange={(e) => void handleUpload(bo, e.target.files)}
                          />
                          <button
                            type="button"
                            onClick={() => fileInputs.current[bo.id]?.click()}
                            disabled={uploadingId === bo.id || bo.so_file >= (data?.max_file_moi_bo ?? 100)}
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-hds-navy text-hds-gold text-xs font-bold hover:bg-hds-navy-light disabled:opacity-50 transition-colors"
                          >
                            {uploadingId === bo.id ? (
                              <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            ) : (
                              <Upload className="w-3.5 h-3.5" />
                            )}
                            Tải file .docx vào bộ
                          </button>
                          {uploadingId === bo.id && (
                            <span className="text-[11px] text-slate-500">Đang tải… {progress}%</span>
                          )}
                          <span className="text-[11px] text-slate-400">
                            Chọn nhiều file một lần; chỉ nhận .docx (file .doc cũ lưu lại thành .docx trước).
                          </span>
                        </div>
                      )}
                      {bo.files.length === 0 ? (
                        <p className="text-xs text-slate-500 dark:text-slate-400">
                          Bộ chưa có file nào. AI cần ít nhất một file .docx để điền.
                        </p>
                      ) : (
                        <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                          {bo.files.map((f) => (
                            <li key={f.id} className="py-2 flex items-start gap-3 text-xs">
                              <FileText className="w-4 h-4 text-hds-navy dark:text-blue-300 shrink-0 mt-0.5" />
                              <div className="flex-1 min-w-0">
                                <div className="font-semibold text-slate-800 dark:text-slate-100 truncate">
                                  {f.thu_tu}. {f.ten_file}
                                </div>
                                <div className="text-[11px] text-slate-500 dark:text-slate-400">
                                  {f.so_placeholder > 0 ? (
                                    <>
                                      {f.so_placeholder} chỗ trống:{' '}
                                      <span className="font-mono">
                                        {f.placeholders.slice(0, 8).join(' ')}
                                        {f.placeholders.length > 8 && ' …'}
                                      </span>
                                    </>
                                  ) : (
                                    <span className="text-amber-600 dark:text-amber-400">
                                      Không có chỗ trống {'{{…}}'} — AI sẽ tự tìm chuỗi cần thay (kém chính xác hơn)
                                    </span>
                                  )}
                                  {' · '}
                                  {Math.round(f.so_ky_tu / 1000)}k ký tự
                                </div>
                              </div>
                              <div className="flex items-center gap-1 shrink-0">
                                <button
                                  type="button"
                                  onClick={() => void api.downloadBoMauFile(bo.id, f.id, f.ten_file).catch((err: any) =>
                                    showToast(err?.message || 'Không tải được file.', 'error'))}
                                  className="p-1.5 rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
                                  title="Tải bản gốc"
                                >
                                  <Download className="w-4 h-4" />
                                </button>
                                {coQuyen && (
                                  <button
                                    type="button"
                                    onClick={() => void handleDeleteFile(bo, f.id, f.ten_file)}
                                    className="p-1.5 rounded-lg text-red-600 hover:bg-red-50 dark:hover:bg-red-950"
                                    title="Gỡ file khỏi bộ"
                                  >
                                    <Trash2 className="w-4 h-4" />
                                  </button>
                                )}
                              </div>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>

      {dienBo && (
        <div
          className="fixed inset-0 z-50 bg-slate-950/60 backdrop-blur-sm flex items-center justify-center p-4"
          onClick={() => setDienBo(null)}
          role="presentation"
        >
          <div
            onClick={(event) => event.stopPropagation()}
            className="w-full max-w-3xl max-h-[90vh] overflow-y-auto bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-2xl"
          >
            <div className="p-5 border-b border-slate-200 dark:border-slate-800 flex items-start justify-between gap-3">
              <div>
                <h3 className="font-bold text-base">Điền bộ hồ sơ «{dienBo.ten}»</h3>
                <p className="text-[11px] text-slate-500 mt-0.5">
                  Điền dữ liệu vào các file Word của bộ, giữ nguyên định dạng gốc.
                </p>
              </div>
              <button type="button" onClick={() => setDienBo(null)} aria-label="Đóng">
                <X className="w-5 h-5 text-slate-400" />
              </button>
            </div>
            <div className="p-5">
              <DienBoMauPanel bo={dienBo} onClose={() => setDienBo(null)} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
