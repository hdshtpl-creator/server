import React, { useState } from 'react';
import { useApp } from '../../context/AppContext';
import {
  Lock,
  Mail,
  Shield,
  AlertCircle,
  ArrowRight,
  Loader2,
  Info,
  Eye,
  EyeOff,
} from 'lucide-react';

/**
 * Tài khoản mẫu tạo bởi `python -m app.seed_accounts` của backend hds-ai.
 * Chỉ điền sẵn email — mật khẩu do người dùng tự nhập, không nhúng vào mã nguồn.
 */
const DEMO_ACCOUNTS = [
  { email: 'admin@hdslaw.vn', label: 'Quản trị hệ thống', accent: 'border-red-500/30 text-red-300' },
  { email: 'giamdoc@hdslaw.vn', label: 'Giám đốc (Ban QT)', accent: 'border-purple-500/30 text-purple-300' },
  { email: 'truong.dndt@hdslaw.vn', label: 'Trưởng phòng DN-ĐT', accent: 'border-amber-500/30 text-amber-300' },
  { email: 'cv.tranhtung@hdslaw.vn', label: 'Chuyên viên Tranh tụng', accent: 'border-blue-500/30 text-blue-300' },
  { email: 'troly@hdslaw.vn', label: 'Trợ lý pháp chế', accent: 'border-emerald-500/30 text-emerald-300' },
];

export const LoginScreen: React.FC = () => {
  const { login, showToast, isMockMode } = useApp();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password) {
      setErrorMessage('Vui lòng nhập đầy đủ email và mật khẩu.');
      return;
    }

    setIsLoading(true);
    setErrorMessage(null);

    try {
      await login(email.trim(), password);
      showToast('Đăng nhập thành công. Chào mừng bạn đến với HDS AI.', 'success');
    } catch (err: any) {
      setErrorMessage(err?.message || 'Không đăng nhập được. Vui lòng thử lại.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 flex items-center justify-center p-4 relative overflow-hidden font-sans">
      {/* Nền trang trí */}
      <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-hds-navy/50 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-hds-gold/10 rounded-full blur-3xl pointer-events-none" />

      <div className="w-full max-w-md relative z-10 space-y-6 py-8">
        {/* Thương hiệu */}
        <div className="text-center space-y-2">
          <div className="inline-flex items-center justify-center gap-1.5 p-3 bg-white rounded-2xl shadow-xl border-2 border-hds-gold">
            <span className="text-hds-navy text-3xl font-black tracking-tight leading-none">
              HDS
            </span>
            <span className="text-xs uppercase tracking-widest bg-hds-navy text-white px-2 py-1 rounded font-bold leading-none">
              AI Legal
            </span>
          </div>
          <h1 className="text-2xl font-black tracking-tight text-white">CÔNG TY LUẬT HDS</h1>
          <p className="text-xs text-slate-400">
            Hệ thống trợ lý AI nội bộ và tra cứu tri thức pháp lý
          </p>
        </div>

        {/* Khung đăng nhập */}
        <div className="bg-slate-800/90 backdrop-blur-md rounded-2xl border border-slate-700 p-6 sm:p-8 shadow-2xl space-y-5">
          <div className="flex items-center justify-between gap-3 pb-3 border-b border-slate-700">
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <Shield className="w-5 h-5 text-hds-gold" />
              <span>Đăng nhập hệ thống</span>
            </h2>
            {isMockMode && (
              <span className="text-[10px] bg-hds-gold/20 text-amber-200 px-2 py-0.5 rounded font-bold border border-hds-gold/40 shrink-0">
                Dữ liệu giả lập
              </span>
            )}
          </div>

          {errorMessage && (
            <div
              role="alert"
              className="p-3 bg-red-950/80 border border-red-800 rounded-xl text-red-200 text-xs flex items-start gap-2.5 animate-shake"
            >
              <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-px" />
              <span className="font-semibold">{errorMessage}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4 text-xs">
            <div className="space-y-1">
              <label htmlFor="login-email" className="block font-semibold text-slate-300">
                Email tài khoản
              </label>
              <div className="relative flex items-center">
                <Mail className="w-4 h-4 text-slate-400 absolute left-3 pointer-events-none" />
                <input
                  id="login-email"
                  type="email"
                  required
                  autoComplete="username"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="ten.ban@hdslaw.vn"
                  className="w-full pl-9 pr-3 py-2.5 bg-slate-900/80 border border-slate-700 rounded-xl text-slate-100 placeholder-slate-500 focus:outline-none focus:border-hds-gold focus:ring-2 focus:ring-hds-gold/30 text-xs font-mono transition-colors"
                />
              </div>
            </div>

            <div className="space-y-1">
              <label htmlFor="login-password" className="block font-semibold text-slate-300">
                Mật khẩu
              </label>
              <div className="relative flex items-center">
                <Lock className="w-4 h-4 text-slate-400 absolute left-3 pointer-events-none" />
                <input
                  id="login-password"
                  type={showPassword ? 'text' : 'password'}
                  required
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full pl-9 pr-10 py-2.5 bg-slate-900/80 border border-slate-700 rounded-xl text-slate-100 placeholder-slate-500 focus:outline-none focus:border-hds-gold focus:ring-2 focus:ring-hds-gold/30 text-xs transition-colors"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-2 p-1.5 text-slate-400 hover:text-slate-200 transition-colors"
                  aria-label={showPassword ? 'Ẩn mật khẩu' : 'Hiện mật khẩu'}
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="w-full py-3 px-4 bg-hds-navy hover:bg-hds-navy-light text-hds-gold font-bold rounded-xl shadow-lg border border-hds-gold/30 flex items-center justify-center gap-2 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {isLoading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Đang xác thực…</span>
                </>
              ) : (
                <>
                  <span>Đăng nhập</span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </form>

          {/* Điền nhanh email tài khoản mẫu */}
          <div className="pt-4 border-t border-slate-700 space-y-2">
            <p className="text-[11px] font-semibold text-slate-400 text-center">
              Điền nhanh email tài khoản mẫu
            </p>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px]">
              {DEMO_ACCOUNTS.map((acc) => (
                <button
                  key={acc.email}
                  type="button"
                  onClick={() => setEmail(acc.email)}
                  className={`p-2 rounded-lg bg-slate-900/60 hover:bg-slate-700 border text-left transition-colors ${acc.accent}`}
                >
                  <span className="font-bold block">{acc.label}</span>
                  <span className="text-[10px] text-slate-400 font-mono block truncate">
                    {acc.email}
                  </span>
                </button>
              ))}
            </div>

            <div className="flex items-start gap-2 text-[10px] text-slate-400 bg-slate-900/50 border border-slate-700 rounded-lg p-2.5">
              <Info className="w-3.5 h-3.5 shrink-0 mt-px text-hds-gold" />
              <span>
                Mật khẩu do backend cấp khi chạy{' '}
                <code className="font-mono text-slate-300">python -m app.seed_accounts</code>. Hãy
                đổi mật khẩu ngay sau lần đăng nhập đầu tiên.
              </span>
            </div>
          </div>
        </div>

        <p className="text-[11px] text-slate-500 text-center">
          © {new Date().getFullYear()} HDS Law Firm — Phân quyền dữ liệu bằng PostgreSQL Row Level
          Security
        </p>
      </div>
    </div>
  );
};
