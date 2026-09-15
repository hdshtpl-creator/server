import React from 'react';
import { AppProvider, useApp } from './context/AppContext';
import { Header } from './components/Header';
import { BanMoiBanner } from './components/BanMoiBanner';
import { ToastContainer } from './components/ToastContainer';
import { ChatLayout } from './components/chat/ChatLayout';
import { AdminLayout } from './components/admin/AdminLayout';
import { LoginScreen } from './components/auth/LoginScreen';
import { canAccessAdmin } from './constants';
import { Loader2 } from 'lucide-react';

const DraftsWorkspace = React.lazy(() =>
  import('./components/drafts/DraftsWorkspace').then((module) => ({
    default: module.DraftsWorkspace,
  }))
);

const LegalCheckWorkspace = React.lazy(() =>
  import('./components/legal/LegalCheckWorkspace').then((module) => ({
    default: module.LegalCheckWorkspace,
  }))
);

const MainContent: React.FC = () => {
  const { activeView, isAuthenticated, isBootstrapping, currentUser } = useApp();

  // Đang khôi phục phiên từ token đã lưu — tránh chớp màn hình đăng nhập khi F5
  if (isBootstrapping) {
    return (
      <div className="min-h-screen bg-hds-navy flex flex-col items-center justify-center gap-3 text-blue-100">
        <Loader2 className="w-8 h-8 animate-spin text-hds-gold" />
        <p className="text-sm">Đang khôi phục phiên đăng nhập…</p>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <>
        <LoginScreen />
        <ToastContainer />
      </>
    );
  }

  // Chặn ở tầng giao diện luôn, khớp với require_reviewer / require(admin) của backend
  const showAdmin = activeView === 'admin' && canAccessAdmin(currentUser);
  const showDrafts = activeView === 'drafts' && currentUser && !currentUser.role.startsWith('client_');
  const showLegal = activeView === 'legal' && currentUser && !currentUser.role.startsWith('client_');

  return (
    <div className="min-h-screen bg-hds-soft dark:bg-slate-950 flex flex-col text-slate-900 dark:text-slate-100 font-sans antialiased">
      {/* Deploy bản mới mà tab này còn chạy bản cũ → dải vàng mời tải lại */}
      <BanMoiBanner />
      <Header />
      <div className="flex-1 flex flex-col min-h-0">
        {showAdmin ? (
          <AdminLayout />
        ) : showLegal ? (
          <React.Suspense
            fallback={
              <div className="flex-1 flex items-center justify-center gap-2 text-sm text-slate-500">
                <Loader2 className="w-5 h-5 animate-spin" /> Đang mở khu kiểm tra pháp lý…
              </div>
            }
          >
            <LegalCheckWorkspace />
          </React.Suspense>
        ) : showDrafts ? (
          <React.Suspense
            fallback={
              <div className="flex-1 flex items-center justify-center gap-2 text-sm text-slate-500">
                <Loader2 className="w-5 h-5 animate-spin" /> Đang mở khu soạn tài liệu…
              </div>
            }
          >
            <DraftsWorkspace />
          </React.Suspense>
        ) : (
          <ChatLayout />
        )}
      </div>
      <ToastContainer />
    </div>
  );
};

export default function App() {
  return (
    <AppProvider>
      <MainContent />
    </AppProvider>
  );
}
