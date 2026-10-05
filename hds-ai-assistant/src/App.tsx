import React from 'react';
import { AppProvider, useApp } from './context/AppContext';
import { Header } from './components/Header';
import { BanMoiBanner } from './components/BanMoiBanner';
import { ToastContainer } from './components/ToastContainer';
import { ChatLayout } from './components/chat/ChatLayout';
import { AdminLayout } from './components/admin/AdminLayout';
import { LoginScreen } from './components/auth/LoginScreen';
import { ChangePasswordModal } from './components/auth/ChangePasswordModal';
import { canAccessAdmin, coTinhNang } from './constants';
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

  // Đang dùng mật khẩu tạm do quản trị cấp (vừa tạo / vừa đặt lại): máy chủ
  // trả 403 cho MỌI cửa trừ GET /auth/me và POST /auth/change-password. Dựng
  // khung chat / Quản trị phía sau hộp đổi mật khẩu là kéo theo cả loạt lời
  // gọi nạp dữ liệu (hội thoại, model, mẫu phương pháp, bộ mẫu, thống kê…) —
  // cái nào cũng 403 và bắn toast đỏ chồng lên hộp. Nên chỉ dựng nền trống +
  // hộp đổi mật khẩu. Hộp không đóng được cho tới khi đổi xong — refreshMe()
  // sau đó tắt cờ, trang dựng lại đầy đủ và nạp dữ liệu như thường.
  if (currentUser?.must_change_password) {
    return (
      <div className="min-h-screen bg-hds-navy flex flex-col text-slate-900 dark:text-slate-100 font-sans antialiased">
        <ToastContainer />
        <ChangePasswordModal isOpen forced onClose={() => {}} />
      </div>
    );
  }

  // Chặn ở tầng giao diện luôn, khớp với require_reviewer / require(admin) của backend
  const showAdmin = activeView === 'admin' && canAccessAdmin(currentUser);
  // Khách VÀO ĐƯỢC hai khu này nếu quản trị đã bật chức năng tương ứng
  // (20/09/2026). Backend chặn lần nữa nên đây chỉ là ẩn/hiện.
  const showDrafts = activeView === 'drafts' && coTinhNang(currentUser, 'soan_thao');
  const showLegal = activeView === 'legal' && coTinhNang(currentUser, 'kiem_tra');

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
