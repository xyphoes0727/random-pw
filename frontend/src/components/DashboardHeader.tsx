import { Shield, User, LogOut, Bell } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/contexts/AuthContext";
import { useAlerts } from "@/contexts/AlertContext";
import { useState } from "react";
import { AuthDialog } from "./AuthDialog";
import { BASE_URL_HTTP, BASE_URL_WEBSOCKET } from "../config";

interface DashboardHeaderProps {
  onNavigateToAudits?: () => void;
}

export const DashboardHeader = ({ onNavigateToAudits }: DashboardHeaderProps) => {
  const { isAuthenticated, username, logout } = useAuth();
  const { unreadCount } = useAlerts();
  const [authDialogOpen, setAuthDialogOpen] = useState(false);
  const [authDialogTab, setAuthDialogTab] = useState<'login' | 'signup'>('login');

  const openAuthDialog = (tab: 'login' | 'signup') => {
    setAuthDialogTab(tab);
    setAuthDialogOpen(true);
  };

  return (
    <>
      <header className="border-b border-border bg-black">
        <div className="container mx-auto px-6 py-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary">
                <Shield className="h-6 w-6 text-primary-foreground" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-foreground">Fraud Detection</h1>
                <p className="text-sm text-muted-foreground">Real-time monitoring system</p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              {/* Alert Bell */}
              {isAuthenticated && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="relative"
                  onClick={onNavigateToAudits}
                >
                  <Bell className="h-5 w-5" />
                  {unreadCount > 0 && (
                    <span className="absolute -top-1 -right-1 h-5 w-5 flex items-center justify-center bg-destructive text-destructive-foreground text-xs font-bold rounded-full">
                      {unreadCount > 9 ? '9+' : unreadCount}
                    </span>
                  )}
                </Button>
              )}
              
              {isAuthenticated ? (
                <>
                  <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-muted">
                    <User className="h-4 w-4" />
                    <span className="text-sm font-medium">{username}</span>
                  </div>
                  <Button variant="ghost" size="sm" onClick={logout} className="gap-2">
                    <LogOut className="h-4 w-4" />
                    Logout
                  </Button>
                </>
              ) : (
                <>
                  <Button variant="ghost" size="sm" onClick={() => openAuthDialog('login')}>
                    Login
                  </Button>
                  <Button variant="default" size="sm" onClick={() => openAuthDialog('signup')}>
                    Sign Up
                  </Button>
                </>
              )}
            </div>
          </div>
        </div>
      </header>
      <AuthDialog 
        open={authDialogOpen} 
        onOpenChange={setAuthDialogOpen}
        defaultTab={authDialogTab}
      />
    </>
  );
};
