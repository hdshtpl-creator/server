import React, { useState, useRef, useEffect } from 'react';
import { useApp } from '../context/AppContext';
import { ChangePasswordModal } from './auth/ChangePasswordModal';
import { ROLE_META, canAccessAdmin } from '../constants';
import {
  MessageSquare,
  ShieldCheck,
  Settings,
  Server,
  ChevronDown,
  Info,
  Sliders,
  CheckCircle2,
  Sun,
  Moon,
  LogOut,
  KeyRound,
  Menu,
  X,
  UserCircle2,
} from 'lucide-react';

export const Header: React.FC = () => {
  const {
    currentUser,
    activeView,
    setActiveView,
    apiBaseUrl,
    setApiBaseUrl,
    isMockMode,
    setIsMockMode,
    isDarkMode,
    toggleDarkMode,
    showToast,
    logout,
    isSidebarOpen,
    setSidebarOpen,
  } = useApp();

  const [showConfigModal, setShowConfigModal] = useState(false);
  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [tempUrl, setTempUrl] = useState(apiBaseUrl);

  const userMenuRef = useRef<HTMLDivElement>(null);

  // Đóng menu người dùng khi bấm ra ngoài hoặc nhấn Esc
  useEffect(() => {
    if (!showUserMenu) return;
    const onPointerDown = (e: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setShowUserMenu(false);
      }
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowUserMenu(false);
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [showUserMenu]);

  useEffect(() => {
    setTempUrl(apiBaseUrl);
  }, [apiBaseUrl]);

  const handleSaveConfig = () => {
    const url = tempUrl.trim();
    if (!/^https?:\/\//i.test(url)) {
      showToast('Địa chỉ backend phải bắt đầu bằng http:// hoặc https://', 'error');
      return;
    }
    setApiBaseUrl(url);
    setShowConfigModal(false);
    showToast(`Đã lưu địa chỉ backend: ${url}`, 'success');
  };

  const role = ROLE_META[currentUser?.role as keyof typeof ROLE_META];
  const showAdminTab = canAccessAdmin(currentUser);

  const tabClass = (active: boolean) =>
    `flex items-center gap-2 px-3 sm:px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
      active
        ? 'bg-hds-gold text-hds-navy font-semibold shadow-sm'
        : 'text-blue-100 hover:text-white hover:bg-white/10'
    }`;

  return (
    <>
      <header className="bg-hds-navy text-white shadow-md sticky top-0 z-40">
        <div className="mx-auto max-w-[1600px] px-3 sm:px-4 lg:px-6 h-16 flex items-center gap-3">
          {/* Nút mở danh sách hội thoại — chỉ hiện ở màn hình hẹp, trong màn Chat */}
          {activeView === 'chat' && (
            <button
              onClick={() => setSidebarOpen(!isSidebarOpen)}
              className="lg:hidden p-2 -ml-1 rounded-lg text-blue-100 hover:bg-white/10 transition-colors"
              aria-label={isSidebarOpen ? 'Đóng danh sách hội thoại' : 'Mở danh sách hội thoại'}
              aria-expanded={isSidebarOpen}
            >
              {isSidebarOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
            </button>
          )}

          {/* Thương hiệu */}
          <div className="flex items-center gap-3 shrink-0">
            <div className="bg-white rounded px-2 py-1 flex items-center gap-1.5 shadow-sm border border-hds-gold/70">
              <span className="text-hds-navy text-lg font-black tracking-tight leading-none">
                HDS
              </span>
              <span className="text-[10px] uppercase tracking-widest bg-hds-navy text-white px-1.5 py-0.5 rounded font-bold leading-none">
                AI
              </span>
            </div>
            <div className="hidden md:block border-l border-white/20 pl-3">
              <h1 className="text-sm font-semibold tracking-wide">CÔNG TY LUẬT HDS</h1>
              <p className="text-[10px] text-blue-200">
                Nhanh nhờ công nghệ — Vững nhờ luật sư
              </p>
            </div>
          </div>

          {/* Điều hướng chính */}
          <nav className="flex items-center gap-1 bg-hds-navy-dark/70 p-1 rounded-xl border border-white/10 mx-auto">
            <button
              id="nav-chat-btn"
              onClick={() => setActiveView('chat')}
              className={tabClass(activeView === 'chat')}
              aria-current={activeView === 'chat' ? 'page' : undefined}
            >
              <MessageSquare className="w-4 h-4" />
              <span className="hidden sm:inline">Hội thoại AI</span>
            </button>

            {showAdminTab && (
              <button
                id="nav-admin-btn"
                onClick={() => setActiveView('admin')}
                className={tabClass(activeView === 'admin')}
                aria-current={activeView === 'admin' ? 'page' : undefined}
              >
                <ShieldCheck className="w-4 h-4" />
                <span className="hidden sm:inline">Quản trị</span>
              </button>
            )}
          </nav>

          {/* Công cụ bên phải */}
          <div className="flex items-center gap-1.5 sm:gap-2 shrink-0">
            {/* Trạng thái kết nối backend */}
            <button
              id="api-config-btn"
              onClick={() => setShowConfigModal(true)}
              className={`hidden sm:flex text-xs px-2.5 py-1.5 rounded-lg border font-medium items-center gap-1.5 transition-colors ${
                isMockMode
                  ? 'bg-hds-gold/20 text-amber-100 border-hds-gold/50 hover:bg-hds-gold/30'
                  : 'bg-emerald-500/20 text-emerald-100 border-emerald-400/40 hover:bg-emerald-500/30'
              }`}
              title="Cấu hình kết nối backend FastAPI"
            >
              <Server className="w-3.5 h-3.5" />
              <span className="hidden lg:inline">
                {isMockMode ? 'Dữ liệu giả lập' : 'Backend FastAPI'}
              </span>
              <Settings className="w-3 h-3 opacity-70" />
            </button>

            {/* Sáng / tối */}
            <button
              id="theme-toggle-btn"
              onClick={toggleDarkMode}
              className="p-2 rounded-lg bg-white/10 border border-white/15 hover:bg-white/20 transition-colors"
              title={isDarkMode ? 'Chuyển sang chế độ sáng' : 'Chuyển sang chế độ tối'}
              aria-label={isDarkMode ? 'Chuyển sang chế độ sáng' : 'Chuyển sang chế độ tối'}
            >
              {isDarkMode ? (
                <Sun className="w-4 h-4 text-hds-gold" />
              ) : (
                <Moon className="w-4 h-4 text-blue-100" />
              )}
            </button>

            {/* Menu tài khoản */}
            <div className="relative" ref={userMenuRef}>
              <button
                onClick={() => setShowUserMenu((v) => !v)}
                className="flex items-center gap-2 pl-2 pr-1.5 py-1.5 rounded-lg bg-white/10 border border-white/15 hover:bg-white/20 transition-colors"
                aria-haspopup="menu"
                aria-expanded={showUserMenu}
              >
                <UserCircle2 className="w-5 h-5 text-hds-gold shrink-0" />
                <span className="hidden md:flex flex-col items-start leading-tight max-w-[11rem]">
                  <span className="text-xs font-semibold truncate w-full text-left">
                    {currentUser?.full_name || 'Người dùng'}
                  </span>
                  <span className="text-[10px] text-blue-200">
                    {role?.label || currentUser?.role}
                  </span>
                </span>
                <ChevronDown className="w-3.5 h-3.5 text-blue-200" />
              </button>

              {showUserMenu && (
                <div
                  role="menu"
                  className="absolute right-0 mt-2 w-72 bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-100 rounded-xl shadow-2xl border border-slate-200 dark:border-slate-700 overflow-hidden animate-pop-in"
                >
                  <div className="p-4 border-b border-slate-100 dark:border-slate-800">
                    <p className="font-bold text-sm truncate">
                      {currentUser?.full_name || 'Người dùng'}
                    </p>
                    <p className="text-xs text-slate-500 dark:text-slate-400 truncate">
                      {currentUser?.email || `Mã tài khoản: ${currentUser?.id ?? '—'}`}
                    </p>
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      <span
                        className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${
                          role?.badge || 'bg-slate-100 text-slate-700 border-slate-300'
                        }`}
                      >
                        {role?.label || currentUser?.role}
                      </span>
                      {currentUser?.can_review && (
                        <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full border bg-emerald-100 text-emerald-800 border-emerald-300 dark:bg-emerald-950 dark:text-emerald-300 dark:border-emerald-800">
                          Có quyền duyệt
                        </span>
                      )}
                    </div>
                  </div>

                  <button
                    role="menuitem"
                    onClick={() => {
                      setShowUserMenu(false);
                      setShowPasswordModal(true);
                    }}
                    className="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
                  >
                    <KeyRound className="w-4 h-4 text-hds-blue" />
                    <span>Đổi mật khẩu</span>
                  </button>

                  <button
                    role="menuitem"
                    onClick={() => {
                      setShowUserMenu(false);
                      setShowConfigModal(true);
                    }}
                    className="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors sm:hidden"
                  >
                    <Server className="w-4 h-4 text-hds-blue" />
                    <span>Cấu hình backend</span>
                  </button>

                  <button
                    role="menuitem"
                    onClick={() => {
                      setShowUserMenu(false);
                      logout();
                    }}
                    className="w-full flex items-center gap-2.5 px-4 py-2.5 text-sm text-hds-red dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/50 border-t border-slate-100 dark:border-slate-800 transition-colors"
                  >
                    <LogOut className="w-4 h-4" />
                    <span className="font-semibold">Đăng xuất</span>
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      </header>

      <ChangePasswordModal isOpen={showPasswordModal} onClose={() => setShowPasswordModal(false)} />

      {/* Cấu hình kết nối backend */}
      {showConfigModal && (
        <div
          className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center z-50 p-4 animate-fade-in"
          onClick={() => setShowConfigModal(false)}
          role="presentation"
        >
          <div
            className="bg-white dark:bg-slate-900 rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-700 w-full max-w-lg p-6 text-slate-800 dark:text-slate-100 animate-pop-in max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="config-modal-title"
          >
            <div className="flex items-start justify-between pb-4 border-b border-slate-100 dark:border-slate-800">
              <div className="flex items-center gap-2.5">
                <div className="p-2 bg-hds-soft dark:bg-hds-navy text-hds-navy dark:text-blue-200 rounded-lg">
                  <Sliders className="w-5 h-5" />
                </div>
                <div>
                  <h3 id="config-modal-title" className="font-bold text-lg">
                    Cấu hình kết nối
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Backend FastAPI hoặc dữ liệu giả lập
                  </p>
                </div>
              </div>
              <button
                onClick={() => setShowConfigModal(false)}
                className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 p-1"
                aria-label="Đóng"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="mt-4 space-y-4 text-xs">
              <div>
                <label
                  htmlFor="api-base-url"
                  className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1"
                >
                  Địa chỉ backend FastAPI
                </label>
                <input
                  id="api-base-url"
                  type="url"
                  value={tempUrl}
                  onChange={(e) => setTempUrl(e.target.value)}
                  placeholder="http://localhost:8000"
                  className="w-full px-3 py-2 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 rounded-lg focus:ring-2 focus:ring-hds-blue focus:outline-none font-mono text-xs"
                />
                <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-1">
                  Mặc định{' '}
                  <code className="bg-slate-100 dark:bg-slate-800 px-1 rounded">
                    http://localhost:8000
                  </code>
                  . Mọi request đều tự đính kèm{' '}
                  <code className="bg-slate-100 dark:bg-slate-800 px-1 rounded">
                    Authorization: Bearer
                  </code>
                  .
                </p>
              </div>

              <div className="p-3.5 bg-slate-50 dark:bg-slate-800/60 rounded-xl border border-slate-200 dark:border-slate-700 flex items-center justify-between gap-3">
                <div>
                  <div className="font-semibold text-xs flex items-center gap-1.5">
                    <span>Chế độ dữ liệu giả lập</span>
                    {isMockMode && (
                      <span className="text-[10px] bg-hds-gold/20 text-amber-800 dark:text-amber-300 border border-hds-gold/40 px-1.5 py-0.5 rounded font-bold">
                        Đang bật
                      </span>
                    )}
                  </div>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
                    Thử toàn bộ tính năng bằng dữ liệu mẫu khi backend chưa chạy.
                  </p>
                </div>
                <label className="relative inline-flex items-center cursor-pointer shrink-0">
                  <input
                    type="checkbox"
                    checked={isMockMode}
                    onChange={(e) => setIsMockMode(e.target.checked)}
                    className="sr-only peer"
                    aria-label="Bật chế độ dữ liệu giả lập"
                  />
                  <div className="w-11 h-6 bg-slate-300 dark:bg-slate-700 rounded-full peer peer-checked:bg-hds-navy peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-0.5 after:left-0.5 after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-transform" />
                </label>
              </div>

              <div className="p-3 bg-hds-soft dark:bg-slate-800/60 border border-blue-200 dark:border-slate-700 rounded-lg text-xs text-hds-navy dark:text-blue-200 flex items-start gap-2">
                <Info className="w-4 h-4 shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <p className="font-semibold">Phiên đăng nhập hiện tại</p>
                  <p>
                    {currentUser?.full_name || 'Chưa xác định'} —{' '}
                    {role?.label || currentUser?.role || '—'} (mã{' '}
                    <span className="font-mono font-bold">{currentUser?.id ?? '—'}</span>).
                  </p>
                  <p className="text-[11px] opacity-80">
                    Backend xác thực bằng JWT, quyền hạn lấy từ token nên không thể đổi vai bằng
                    cách sửa header.
                  </p>
                </div>
              </div>
            </div>

            <div className="mt-6 flex justify-end gap-2 pt-3 border-t border-slate-100 dark:border-slate-800">
              <button
                onClick={() => setShowConfigModal(false)}
                className="px-4 py-2 border border-slate-300 dark:border-slate-700 rounded-lg text-xs font-semibold text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
              >
                Đóng
              </button>
              <button
                onClick={handleSaveConfig}
                className="px-4 py-2 bg-hds-navy hover:bg-hds-navy-light text-white rounded-lg text-xs font-semibold shadow-sm flex items-center gap-1.5 transition-colors"
              >
                <CheckCircle2 className="w-4 h-4" />
                <span>Lưu thay đổi</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
