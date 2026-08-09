import React from 'react';
import { useApp } from '../../context/AppContext';
import { OverviewTab } from './OverviewTab';
import { DocumentReviewTab } from './DocumentReviewTab';
import { LearnReviewTab } from './LearnReviewTab';
import { MethodTemplatesTab } from './MethodTemplatesTab';
import { UserManagementTab } from './UserManagementTab';
import { LearnedDocsTab } from './LearnedDocsTab';
import { Client360Tab } from './Client360Tab';
import { BrowseDocsTab } from './BrowseDocsTab';
import {
  LayoutDashboard,
  FileCheck2,
  MessageSquareText,
  Boxes,
  Users,
  BookOpen,
  ShieldAlert,
  Users2,
  Search,
} from 'lucide-react';

export const AdminLayout: React.FC = () => {
  const { adminTab, setAdminTab, currentUser } = useApp();

  const isAdmin = currentUser?.role === 'admin';

  const tabs = [
    { id: 'overview', label: 'Tổng quan', icon: LayoutDashboard, adminOnly: false },
    { id: 'clients_360', label: 'Hồ sơ khách 360°', icon: Users2, adminOnly: false },
    { id: 'browse_docs', label: 'Tra cứu tài liệu', icon: Search, adminOnly: false },
    { id: 'review', label: 'Duyệt nhãn tài liệu', icon: FileCheck2, adminOnly: false },
    { id: 'learn', label: 'Duyệt hội thoại AI', icon: MessageSquareText, adminOnly: false },
    { id: 'methods', label: 'Mẫu phương pháp', icon: Boxes, adminOnly: false },
    { id: 'documents', label: 'Kho tài liệu đã học', icon: BookOpen, adminOnly: false },
    // POST/GET /users ở backend require(user, {"admin"}) — vai khác mở ra chỉ nhận 403
    { id: 'users', label: 'Người dùng & Phòng ban', icon: Users, adminOnly: true },
  ].filter((tab) => !tab.adminOnly || isAdmin);

  return (
    <div className="flex-1 bg-hds-soft dark:bg-slate-950 p-4 sm:p-6 lg:p-8">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Nhắc quyền hạn cho người chỉ được xem */}
        {!currentUser?.can_review && currentUser?.role !== 'admin' && (
          <div className="p-4 bg-amber-50 dark:bg-amber-950/40 border border-amber-300 dark:border-amber-800 rounded-2xl text-amber-900 dark:text-amber-200 flex items-start gap-3 text-xs shadow-sm">
            <ShieldAlert className="w-5 h-5 shrink-0 mt-0.5" />
            <div>
              <p className="font-bold">Chế độ xem hạn chế</p>
              <p className="mt-0.5 leading-relaxed">
                Tài khoản <strong>{currentUser?.full_name}</strong> chưa được cấp quyền kiểm duyệt (
                <code className="font-mono">can_review = false</code>). Các thao tác duyệt tài liệu,
                duyệt hội thoại và xem kho tri thức sẽ bị backend từ chối với mã 403. Liên hệ quản
                trị viên nếu bạn cần quyền này.
              </p>
            </div>
          </div>
        )}

        {/* Thanh tab — cuộn ngang trên màn hình hẹp thay vì xuống dòng lộn xộn */}
        <div className="bg-white dark:bg-slate-900 p-2 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div
            className="flex gap-1 overflow-x-auto no-scrollbar"
            role="tablist"
            aria-label="Khu vực quản trị"
          >
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = adminTab === tab.id;

              return (
                <button
                  key={tab.id}
                  id={`admin-tab-${tab.id}`}
                  role="tab"
                  aria-selected={isActive}
                  onClick={() => setAdminTab(tab.id)}
                  className={`flex items-center gap-2 px-3.5 py-2.5 rounded-xl font-semibold text-xs whitespace-nowrap shrink-0 transition-colors ${
                    isActive
                      ? 'bg-hds-navy text-hds-gold shadow-sm'
                      : 'text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800'
                  }`}
                >
                  <Icon className={`w-4 h-4 ${isActive ? '' : 'text-slate-400'}`} />
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Nội dung tab */}
        <div role="tabpanel">
          {adminTab === 'overview' && <OverviewTab />}
          {adminTab === 'clients_360' && <Client360Tab />}
          {adminTab === 'browse_docs' && <BrowseDocsTab />}
          {adminTab === 'review' && <DocumentReviewTab />}
          {adminTab === 'learn' && <LearnReviewTab />}
          {adminTab === 'methods' && <MethodTemplatesTab />}
          {adminTab === 'documents' && <LearnedDocsTab />}
          {adminTab === 'users' && isAdmin && <UserManagementTab />}
        </div>
      </div>
    </div>
  );
};
