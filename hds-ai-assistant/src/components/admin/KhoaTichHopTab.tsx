import React, { useEffect, useMemo, useState } from 'react';
import * as api from '../../api';
import { useApp } from '../../context/AppContext';
import type { KhoaTichHop, KhoaTichHopMoi, QuyenTichHopResponse, User } from '../../types';
import { Ban, Check, Copy, KeyRound, Loader2, Pencil, Plus, RefreshCw, ShieldCheck, X } from 'lucide-react';

/**
 * Khoá API tích hợp (28/09/2026): admin cấp khoá `hdsi_…` cho HỆ THỐNG NGOÀI
 * (CRM, chatbot bên thứ ba), tick từng quyền. Khác "Cấp khoá API" trên thẻ tài
 * khoản khách (khoá `hds_…`, chỉ hỏi đáp thay khách): khoá ở đây không gắn với
 * người dùng, mà gắn với một nguồn dữ liệu và một danh sách quyền.
 *
 * Khoá thật chỉ hiện ĐÚNG MỘT LẦN sau khi cấp — máy chủ giữ bản băm.
 */

const inputClass =
  'w-full px-3 py-2 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 rounded-xl focus:ring-2 focus:ring-hds-blue focus:outline-none transition-colors text-sm';

const NGUON_HOP_LE = /^[a-z0-9][a-z0-9_-]{1,29}$/;

function fmtLuc(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('vi-VN', { hour12: false });
}

interface FormState {
  ten: string;
  nguon: string;
  boMau: string;
  quyen: string[];
  user_id: string;
  ghi_chu: string;
}

const FORM_TRONG: FormState = { ten: '', nguon: 'crm', boMau: 'crm', quyen: [], user_id: '', ghi_chu: '' };

export const KhoaTichHopTab: React.FC = () => {
  const { showToast } = useApp();
  const [quyenInfo, setQuyenInfo] = useState<QuyenTichHopResponse | null>(null);
  const [danhSach, setDanhSach] = useState<KhoaTichHop[]>([]);
  const [taiKhoanKhach, setTaiKhoanKhach] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [thuHoiBusy, setThuHoiBusy] = useState<number | null>(null);
  const [moForm, setMoForm] = useState(false);
  const [form, setForm] = useState<FormState>(FORM_TRONG);
  const [khoaMoi, setKhoaMoi] = useState<KhoaTichHopMoi | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const [q, ds, users] = await Promise.all([
        api.getKhoaTichHopQuyen(),
        api.getKhoaTichHop(),
        api.getUsers().catch(() => [] as User[]),
      ]);
      setQuyenInfo(q);
      setDanhSach(Array.isArray(ds) ? ds : []);
      setTaiKhoanKhach(
        (Array.isArray(users) ? users : []).filter(
          (u) => String(u.role || '').startsWith('client_') && u.active !== false
        )
      );
      // Bộ mẫu mặc định = CRM: tick sẵn để admin chỉ việc đặt tên rồi cấp.
      const crm = q.bo_mau.find((b) => b.ma === 'crm');
      if (crm) setForm((f) => (f.quyen.length ? f : { ...f, quyen: [...crm.quyen] }));
    } catch (err: any) {
      showToast(err?.message || 'Không tải được danh sách khoá tích hợp', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const tenQuyen = useMemo(() => {
    const m: Record<string, string> = {};
    (quyenInfo?.quyen || []).forEach((q) => {
      m[q.ma] = q.ten;
    });
    return m;
  }, [quyenInfo]);

  const chonBoMau = (ma: string) => {
    const bo = quyenInfo?.bo_mau.find((b) => b.ma === ma);
    setForm((f) => ({
      ...f,
      boMau: ma,
      quyen: bo ? [...bo.quyen] : f.quyen,
      nguon: ma === 'crm' ? 'crm' : ma === 'chatbot' && f.nguon === 'crm' ? 'chatbot' : f.nguon,
    }));
  };

  const toggleQuyen = (ma: string) => {
    setForm((f) => ({
      ...f,
      boMau: 'tuy_chon',
      quyen: f.quyen.includes(ma) ? f.quyen.filter((x) => x !== ma) : [...f.quyen, ma],
    }));
  };

  const canChat = form.quyen.includes('chat');

  const submit = async () => {
    const ten = form.ten.trim();
    const nguon = form.nguon.trim().toLowerCase();
    if (!ten) return showToast('Đặt tên khoá để biết cấp cho hệ thống nào.', 'error');
    if (!NGUON_HOP_LE.test(nguon))
      return showToast("Tên nguồn chỉ gồm chữ thường, số, '-' hoặc '_' (2–30 ký tự), ví dụ: crm", 'error');
    if (!form.quyen.length) return showToast('Tick ít nhất một quyền.', 'error');
    if (canChat && !form.user_id)
      return showToast('Quyền hỏi đáp cần chọn một tài khoản khách đại diện.', 'error');
    setBusy(true);
    try {
      const res = await api.taoKhoaTichHop({
        ten,
        nguon,
        quyen: form.quyen,
        user_id: canChat ? Number(form.user_id) : null,
        ghi_chu: form.ghi_chu.trim() || null,
      });
      setKhoaMoi(res);
      setMoForm(false);
      setForm({ ...FORM_TRONG, quyen: [] });
      showToast(`Đã cấp khoá "${ten}". Sao chép ngay — không hiện lại lần nữa.`, 'success');
      await load();
    } catch (err: any) {
      showToast(err?.message || 'Không cấp được khoá', 'error');
    } finally {
      setBusy(false);
    }
  };

  // Sửa quyền của khoá đang dùng: chuỗi khoá giữ nguyên, bên tích hợp không
  // phải cấu hình lại (vd tick thêm quyền nhân viên cho khoá CRM đã cấp).
  const [suaId, setSuaId] = useState<number | null>(null);
  const [suaQuyen, setSuaQuyen] = useState<string[]>([]);
  const [suaBusy, setSuaBusy] = useState(false);

  const batDauSua = (k: KhoaTichHop) => {
    setSuaId(k.id);
    setSuaQuyen([...k.quyen]);
  };

  const luuQuyen = async (k: KhoaTichHop) => {
    if (!suaQuyen.length) return showToast('Khoá phải có ít nhất một quyền.', 'error');
    setSuaBusy(true);
    try {
      const thuTu = (quyenInfo?.quyen || []).map((q) => q.ma);
      await api.suaKhoaTichHop(k.id, { quyen: thuTu.filter((m) => suaQuyen.includes(m)) });
      showToast(`Đã cập nhật quyền của khoá "${k.ten}". Chuỗi khoá không đổi.`, 'success');
      setSuaId(null);
      await load();
    } catch (err: any) {
      showToast(err?.message || 'Không lưu được quyền', 'error');
    } finally {
      setSuaBusy(false);
    }
  };

  const thuHoi = async (k: KhoaTichHop) => {
    if (!window.confirm(`Thu hồi khoá "${k.ten}" (${k.key_dau}…)?\nMọi lời gọi bằng khoá này bị chặn ngay. Dữ liệu đã gửi vẫn giữ nguyên.`)) return;
    setThuHoiBusy(k.id);
    try {
      await api.thuHoiKhoaTichHop(k.id);
      if (khoaMoi && khoaMoi.id === k.id) setKhoaMoi(null);
      showToast(`Đã thu hồi khoá "${k.ten}".`, 'success');
      await load();
    } catch (err: any) {
      showToast(err?.message || 'Không thu hồi được khoá', 'error');
    } finally {
      setThuHoiBusy(null);
    }
  };

  const copy = (text: string, msg: string) => {
    navigator.clipboard
      ?.writeText(text)
      .then(() => showToast(msg, 'success'))
      .catch(() => showToast('Không sao chép được, hãy chọn và copy tay.', 'error'));
  };

  const apiBase = `${window.location.origin}/api`;
  const curlMau = khoaMoi
    ? `curl ${apiBase}/integration/v1/me -H "X-API-Key: ${khoaMoi.khoa}"`
    : '';

  const dangHoatDong = danhSach.filter((k) => k.hoat_dong);
  const daThuHoi = danhSach.filter((k) => !k.hoat_dong);

  return (
    <div className="space-y-6">
      <section className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-bold text-slate-900 dark:text-white flex items-center gap-2">
              <KeyRound className="w-5 h-5 text-hds-gold" />
              Khoá API tích hợp
            </h2>
            <p className="text-xs text-slate-600 dark:text-slate-400 mt-1 leading-relaxed max-w-3xl">
              Cấp cho <strong>hệ thống ngoài</strong> — CRM đẩy hồ sơ khách và hợp đồng vào kho, hay chatbot bên thứ ba
              hỏi trợ lý. Mỗi khoá mang đúng những quyền được tick. Khoá thật chỉ hiện <strong>một lần</strong> sau khi
              cấp; mất thì thu hồi rồi cấp khoá mới cùng tên nguồn — dữ liệu đã gửi vẫn nhận ra. Hướng dẫn cho đội tích
              hợp: <code className="font-mono">deploy/API_TICH_HOP.md</code>.
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={load}
              disabled={loading}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Tải lại
            </button>
            <button
              onClick={() => setMoForm((v) => !v)}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold bg-hds-navy text-hds-gold hover:opacity-90"
            >
              {moForm ? <X className="w-3.5 h-3.5" /> : <Plus className="w-3.5 h-3.5" />}
              {moForm ? 'Đóng' : 'Cấp khoá mới'}
            </button>
          </div>
        </div>

        {khoaMoi && (
          <div className="mt-4 p-4 rounded-2xl border-2 border-amber-400 bg-amber-50 dark:bg-amber-950/40 dark:border-amber-700">
            <p className="text-xs font-bold text-amber-900 dark:text-amber-200 flex items-center gap-2">
              <ShieldCheck className="w-4 h-4" />
              Khoá vừa cấp cho "{khoaMoi.ten}" (nguồn <code className="font-mono">{khoaMoi.nguon}</code>) — sao chép
              ngay, đóng trang là mất.
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <code className="font-mono text-sm px-3 py-2 rounded-xl bg-white dark:bg-slate-900 border border-amber-300 dark:border-amber-700 break-all select-all">
                {khoaMoi.khoa}
              </code>
              <button
                onClick={() => copy(khoaMoi.khoa, 'Đã sao chép khoá tích hợp.')}
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold bg-amber-600 text-white hover:bg-amber-700"
              >
                <Copy className="w-3.5 h-3.5" /> Sao chép khoá
              </button>
              <button
                onClick={() => setKhoaMoi(null)}
                className="text-xs font-semibold text-amber-800 dark:text-amber-300 underline"
              >
                Đã lưu, ẩn đi
              </button>
            </div>
            <p className="mt-3 text-[11px] text-amber-900/80 dark:text-amber-200/80">Thử kết nối (gửi kèm cho đội tích hợp):</p>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <code className="font-mono text-[11px] px-3 py-2 rounded-xl bg-white dark:bg-slate-900 border border-amber-200 dark:border-amber-800 break-all select-all">
                {curlMau}
              </code>
              <button
                onClick={() => copy(curlMau, 'Đã sao chép lệnh thử.')}
                className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-semibold border border-amber-300 dark:border-amber-700 text-amber-900 dark:text-amber-200"
              >
                <Copy className="w-3 h-3" /> Copy
              </button>
            </div>
          </div>
        )}

        {moForm && quyenInfo && (
          <div className="mt-4 p-4 rounded-2xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/40 space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <label className="block">
                <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">Tên khoá</span>
                <input
                  className={`${inputClass} mt-1`}
                  placeholder="CRM (anh Tuấn Anh) — máy chủ production"
                  value={form.ten}
                  onChange={(e) => setForm((f) => ({ ...f, ten: e.target.value }))}
                  maxLength={80}
                />
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">Tên nguồn (không gian mã ngoài)</span>
                <input
                  className={`${inputClass} mt-1 font-mono`}
                  placeholder="crm"
                  value={form.nguon}
                  onChange={(e) => setForm((f) => ({ ...f, nguon: e.target.value }))}
                  maxLength={30}
                />
                <span className="text-[11px] text-slate-500 dark:text-slate-400">
                  Chữ thường, số, gạch. Cấp khoá mới thay khoá cũ thì giữ nguyên tên nguồn để dữ liệu đã gửi vẫn nhận ra.
                </span>
              </label>
            </div>

            <div>
              <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">Bộ quyền mẫu</span>
              <div className="mt-1 flex flex-wrap gap-2">
                {quyenInfo.bo_mau.map((b) => (
                  <button
                    key={b.ma}
                    type="button"
                    onClick={() => chonBoMau(b.ma)}
                    className={`px-3 py-1.5 rounded-xl text-xs font-semibold border transition-colors ${
                      form.boMau === b.ma
                        ? 'bg-hds-navy text-hds-gold border-hds-navy'
                        : 'border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-white dark:hover:bg-slate-800'
                    }`}
                  >
                    {b.ten}
                  </button>
                ))}
                <span
                  className={`px-3 py-1.5 rounded-xl text-xs font-semibold border ${
                    form.boMau === 'tuy_chon'
                      ? 'bg-hds-navy text-hds-gold border-hds-navy'
                      : 'border-dashed border-slate-300 dark:border-slate-700 text-slate-400'
                  }`}
                >
                  Tuỳ chọn
                </span>
              </div>
            </div>

            <div>
              <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">Quyền của khoá</span>
              <div className="mt-1 grid grid-cols-1 md:grid-cols-2 gap-2">
                {quyenInfo.quyen.map((q) => {
                  const on = form.quyen.includes(q.ma);
                  return (
                    <label
                      key={q.ma}
                      className={`flex items-start gap-2 p-2.5 rounded-xl border cursor-pointer ${
                        on
                          ? 'border-hds-blue bg-blue-50/60 dark:bg-blue-950/30'
                          : 'border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900'
                      }`}
                    >
                      <input type="checkbox" className="mt-0.5" checked={on} onChange={() => toggleQuyen(q.ma)} />
                      <span>
                        <span className="block text-xs font-semibold text-slate-800 dark:text-slate-100">
                          {q.ten} <code className="font-mono text-[10px] text-slate-400">{q.ma}</code>
                        </span>
                        <span className="block text-[11px] text-slate-500 dark:text-slate-400 leading-snug">{q.mo_ta}</span>
                      </span>
                    </label>
                  );
                })}
              </div>
            </div>

            {canChat && (
              <label className="block">
                <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">
                  Tài khoản khách đại diện (bắt buộc cho quyền hỏi đáp)
                </span>
                <select
                  className={`${inputClass} mt-1`}
                  value={form.user_id}
                  onChange={(e) => setForm((f) => ({ ...f, user_id: e.target.value }))}
                >
                  <option value="">— chọn tài khoản khách —</option>
                  {taiKhoanKhach.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.full_name || u.email} · {u.email} {u.client_name ? `· ${u.client_name}` : ''}
                    </option>
                  ))}
                </select>
                <span className="text-[11px] text-slate-500 dark:text-slate-400">
                  Câu hỏi qua khoá này chạy như chính khách đó đăng nhập: cùng hạn mức, cùng chức năng, chỉ thấy hồ sơ của
                  khách đó. Chưa có thì tạo ở tab Người dùng & Phòng ban (vai client_*).
                </span>
                {taiKhoanKhach.length === 0 && (
                  <span className="block text-[11px] text-amber-700 dark:text-amber-300 mt-1">
                    Chưa có tài khoản khách nào đang hoạt động.
                  </span>
                )}
              </label>
            )}

            <label className="block">
              <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">Ghi chú (tuỳ chọn)</span>
              <input
                className={`${inputClass} mt-1`}
                placeholder="Người nhận khoá, máy chủ gọi từ đâu…"
                value={form.ghi_chu}
                onChange={(e) => setForm((f) => ({ ...f, ghi_chu: e.target.value }))}
                maxLength={500}
              />
            </label>

            <div className="flex justify-end gap-2">
              <button
                onClick={() => setMoForm(false)}
                className="px-3 py-2 rounded-xl text-xs font-semibold border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200"
              >
                Huỷ
              </button>
              <button
                onClick={submit}
                disabled={busy}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold bg-hds-navy text-hds-gold hover:opacity-90 disabled:opacity-60"
              >
                {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <KeyRound className="w-3.5 h-3.5" />}
                Cấp khoá
              </button>
            </div>
          </div>
        )}
      </section>

      <section className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm p-5">
        <h3 className="text-sm font-bold text-slate-900 dark:text-white">
          Khoá đang hoạt động <span className="text-slate-400 font-normal">({dangHoatDong.length})</span>
        </h3>
        {loading && danhSach.length === 0 ? (
          <p className="mt-3 text-xs text-slate-500 flex items-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin" /> Đang tải…
          </p>
        ) : dangHoatDong.length === 0 ? (
          <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
            Chưa cấp khoá nào. Bấm <strong>Cấp khoá mới</strong>, chọn bộ quyền <em>CRM</em> rồi gửi khoá cho đội CRM.
          </p>
        ) : (
          <ul className="mt-3 space-y-2">
            {dangHoatDong.map((k) => (
              <li
                key={k.id}
                className="p-3 rounded-xl border border-slate-200 dark:border-slate-800 flex flex-wrap items-start justify-between gap-3"
              >
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-slate-900 dark:text-white flex flex-wrap items-center gap-2">
                    {k.ten}
                    <span className="px-2 py-0.5 rounded-lg text-[10px] font-mono bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">
                      nguồn: {k.nguon}
                    </span>
                    <span className="px-2 py-0.5 rounded-lg text-[10px] font-mono bg-slate-100 dark:bg-slate-800 text-slate-500">
                      {k.key_dau}…
                    </span>
                  </p>
                  {suaId === k.id && quyenInfo ? (
                    <div className="mt-2 space-y-2">
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                        {quyenInfo.quyen.map((q) => {
                          const on = suaQuyen.includes(q.ma);
                          const khoaChat = q.ma === 'chat' && !k.user_id;
                          return (
                            <label
                              key={q.ma}
                              title={khoaChat ? 'Quyền hỏi đáp cần tài khoản khách đại diện — cấp khoá mới có chọn tài khoản.' : q.mo_ta}
                              className={`flex items-center gap-2 px-2.5 py-1.5 rounded-lg border text-xs ${
                                on
                                  ? 'border-hds-blue bg-blue-50/60 dark:bg-blue-950/30 text-slate-800 dark:text-slate-100'
                                  : 'border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-300'
                              } ${khoaChat ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
                            >
                              <input
                                id={`sua-quyen-${k.id}-${q.ma}`}
                                type="checkbox"
                                checked={on}
                                disabled={khoaChat}
                                onChange={() =>
                                  setSuaQuyen((ds) => (ds.includes(q.ma) ? ds.filter((x) => x !== q.ma) : [...ds, q.ma]))
                                }
                              />
                              <span className="font-semibold">{q.ten}</span>
                              <code className="font-mono text-[10px] text-slate-400">{q.ma}</code>
                            </label>
                          );
                        })}
                      </div>
                      <div className="flex gap-2">
                        <button
                          onClick={() => luuQuyen(k)}
                          disabled={suaBusy}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-hds-navy text-hds-gold hover:opacity-90 disabled:opacity-60"
                        >
                          {suaBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                          Lưu quyền
                        </button>
                        <button
                          onClick={() => setSuaId(null)}
                          className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200"
                        >
                          Huỷ
                        </button>
                      </div>
                    </div>
                  ) : (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {k.quyen.map((q) => (
                      <span
                        key={q}
                        title={q}
                        className="px-2 py-0.5 rounded-lg text-[10px] font-semibold bg-blue-50 dark:bg-blue-950/40 text-blue-800 dark:text-blue-200 border border-blue-100 dark:border-blue-900"
                      >
                        {tenQuyen[q] || q}
                      </span>
                    ))}
                  </div>
                  )}
                  <p className="mt-1.5 text-[11px] text-slate-500 dark:text-slate-400">
                    Cấp {fmtLuc(k.created_at)} · dùng lần cuối {fmtLuc(k.last_used_at)} · {k.so_lan_goi ?? 0} lượt gọi ·{' '}
                    {k.so_tai_lieu ?? 0} tài liệu đã nhận
                    {k.email ? ` · tài khoản đại diện: ${k.full_name || k.email}${k.client_name ? ` (${k.client_name})` : ''}` : ''}
                    {k.ghi_chu ? ` · ${k.ghi_chu}` : ''}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => (suaId === k.id ? setSuaId(null) : batDauSua(k))}
                  className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800"
                >
                  <Pencil className="w-3.5 h-3.5" />
                  Sửa quyền
                </button>
                <button
                  onClick={() => thuHoi(k)}
                  disabled={thuHoiBusy === k.id}
                  className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold border border-red-200 dark:border-red-900 text-red-700 dark:text-red-300 hover:bg-red-50 dark:hover:bg-red-950/40 disabled:opacity-60"
                >
                  {thuHoiBusy === k.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Ban className="w-3.5 h-3.5" />}
                  Thu hồi
                </button>
                </div>
              </li>
            ))}
          </ul>
        )}

        {daThuHoi.length > 0 && (
          <details className="mt-4">
            <summary className="text-xs font-semibold text-slate-500 dark:text-slate-400 cursor-pointer">
              Khoá đã thu hồi ({daThuHoi.length})
            </summary>
            <ul className="mt-2 space-y-1.5">
              {daThuHoi.map((k) => (
                <li key={k.id} className="text-[11px] text-slate-500 dark:text-slate-400 px-3 py-2 rounded-xl bg-slate-50 dark:bg-slate-950/40">
                  <span className="line-through">{k.ten}</span> · nguồn {k.nguon} · {k.key_dau}… · thu hồi {fmtLuc(k.revoked_at)} ·{' '}
                  {k.so_lan_goi ?? 0} lượt gọi
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>
    </div>
  );
};
