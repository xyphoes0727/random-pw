import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DashboardHeader } from "@/components/DashboardHeader";
import { SummaryTab } from "@/components/SummaryTab";
import { AnalyticsTab } from "@/components/AnalyticsTab";
import AuditsTab from "@/components/AuditsTab";
import { MetricsTab } from "@/components/MetricsTab";
import ObservabilityTab from "@/components/ObservabilityTab";
import ChatbotTab from "@/components/ChatbotTab";
import { useAuth } from "@/contexts/AuthContext";
import { AuthDialog } from "@/components/AuthDialog";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Lock } from "lucide-react";

const Index = () => {
  const [activeTab, setActiveTab] = useState("summary");
  const { isAuthenticated, loading } = useAuth();
  const [showAuthDialog, setShowAuthDialog] = useState(false);

  // Show loading state while checking auth
  if (loading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <p className="text-muted-foreground">Loading...</p>
      </div>
    );
  }

  // Protected tabs that require authentication
  const protectedTabs = ["analytics", "audits", "metrics", "observability", "chatbot"];

  const handleTabChange = (value: string) => {
    if (!isAuthenticated && protectedTabs.includes(value)) {
      setShowAuthDialog(true);
      return;
    }
    setActiveTab(value);
  };

  const navigateToAudits = () => {
    if (!isAuthenticated) {
      setShowAuthDialog(true);
      return;
    }
    setActiveTab("audits");
  };

  return (
    <div className="min-h-screen bg-background">
      <DashboardHeader onNavigateToAudits={navigateToAudits} />
      <main className="container mx-auto px-6 py-4">
        <Tabs value={activeTab} onValueChange={handleTabChange} className="space-y-4">
          <TabsList className="w-full bg-transparent border-b border-border h-auto p-0 rounded-none flex justify-start gap-0">
            <TabsTrigger 
              value="summary" 
              className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none px-6"
            >
              Summary
            </TabsTrigger>
            <TabsTrigger 
              value="analytics"
              className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none px-6"
            >
              Analytics
              {!isAuthenticated && <Lock className="ml-1 h-3 w-3" />}
            </TabsTrigger>
            <TabsTrigger 
              value="audits"
              className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none px-6"
            >
              Audits
              {!isAuthenticated && <Lock className="ml-1 h-3 w-3" />}
            </TabsTrigger>
            <TabsTrigger 
              value="metrics"
              className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none px-6"
            >
              Metrics
              {!isAuthenticated && <Lock className="ml-1 h-3 w-3" />}
            </TabsTrigger>
            <TabsTrigger 
              value="observability"
              className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none px-6"
            >
              Observability
              {!isAuthenticated && <Lock className="ml-1 h-3 w-3" />}
            </TabsTrigger>
            <TabsTrigger 
              value="chatbot"
              className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none px-6"
            >
              AI Assistant
              {!isAuthenticated && <Lock className="ml-1 h-3 w-3" />}
            </TabsTrigger>
          </TabsList>
          <TabsContent value="summary" className="space-y-6">
            <SummaryTab onNavigateToSystem={() => {}} />
          </TabsContent>
          <TabsContent value="analytics" className="space-y-6">
            {isAuthenticated ? (
              <AnalyticsTab />
            ) : (
              <AuthRequiredCard onLogin={() => setShowAuthDialog(true)} />
            )}
          </TabsContent>
          <TabsContent value="audits" className="space-y-6">
            {isAuthenticated ? (
              <AuditsTab />
            ) : (
              <AuthRequiredCard onLogin={() => setShowAuthDialog(true)} />
            )}
          </TabsContent>
          <TabsContent value="metrics" className="space-y-6">
            {isAuthenticated ? (
              <MetricsTab />
            ) : (
              <AuthRequiredCard onLogin={() => setShowAuthDialog(true)} />
            )}
          </TabsContent>
          <TabsContent value="observability" className="space-y-6">
            {isAuthenticated ? (
              <ObservabilityTab />
            ) : (
              <AuthRequiredCard onLogin={() => setShowAuthDialog(true)} />
            )}
          </TabsContent>
          <TabsContent value="chatbot" className="space-y-6">
            {isAuthenticated ? (
              <ChatbotTab />
            ) : (
              <AuthRequiredCard onLogin={() => setShowAuthDialog(true)} />
            )}
          </TabsContent>
        </Tabs>
      </main>

      <AuthDialog open={showAuthDialog} onOpenChange={setShowAuthDialog} />
    </div>
  );
};

const AuthRequiredCard = ({ onLogin }: { onLogin: () => void }) => (
  <Card className="p-12 text-center">
    <Lock className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
    <h3 className="text-xl font-semibold mb-2">Authentication Required</h3>
    <p className="text-muted-foreground mb-6">
      Please login or sign up to access this feature.
    </p>
    <Button onClick={onLogin}>
      Login / Sign Up
    </Button>
  </Card>
);

export default Index;
