"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Sparkles, LayoutTemplate, ArrowRight } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { useDispatch } from "react-redux";
import { setSelectedAgent, setResearchStrategy } from "@/lib/features/runSlice";

export default function AgentsPage() {
    const router = useRouter();
    const dispatch = useDispatch();
    const { t } = useTranslation();

    const handleSelectAgent = (agentType: "normal" | "card_template") => {
        dispatch(setSelectedAgent(agentType));
        if (agentType === "card_template") {
            dispatch(setResearchStrategy("standard"));
        }
        router.push("/run-detail?session_id=new");
    };

    return (
        <div className="p-4 sm:p-8 space-y-6 sm:space-y-8">
            <div>
                <h1 className="text-3xl font-bold tracking-tight">{t("agentsPage.title")}</h1>
                <p className="text-muted-foreground">
                    {t("agentsPage.subtitle")}
                </p>
            </div>

            <div className="grid gap-6 md:grid-cols-2 max-w-4xl">
                {/* Everyday Agent */}
                <Card className="group hover:border-amber-300 hover:shadow-lg transition-all cursor-pointer" onClick={() => handleSelectAgent("normal")}>
                    <CardHeader>
                        <div className="flex items-center gap-3">
                            <div className="p-3 rounded-xl bg-amber-100 dark:bg-amber-900/30">
                                <Sparkles className="h-6 w-6 text-amber-500" />
                            </div>
                            <div>
                                <CardTitle className="text-xl">{t("agentsPage.everydayTitle")}</CardTitle>
                                <CardDescription>{t("agentsPage.everydayDesc")}</CardDescription>
                            </div>
                        </div>
                    </CardHeader>
                    <CardContent className="space-y-4">
                        <p className="text-sm text-muted-foreground">
                            {t("agentsPage.everydayBody")}
                        </p>
                        <ul className="text-sm space-y-2">
                            <li className="flex items-center gap-2">
                                <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                                {t("agentsPage.everydayPoint1")}
                            </li>
                            <li className="flex items-center gap-2">
                                <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                                {t("agentsPage.everydayPoint2")}
                            </li>
                            <li className="flex items-center gap-2">
                                <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                                {t("agentsPage.everydayPoint3")}
                            </li>
                        </ul>
                        <Button variant="ghost" className="w-full group-hover:bg-amber-50 dark:group-hover:bg-amber-900/20">
                            {t("agentsPage.everydayAction")}
                            <ArrowRight className="ml-2 h-4 w-4" />
                        </Button>
                    </CardContent>
                </Card>

                {/* Template Builder Agent */}
                <Card className="group hover:border-violet-300 hover:shadow-lg transition-all cursor-pointer" onClick={() => handleSelectAgent("card_template")}>
                    <CardHeader>
                        <div className="flex items-center gap-3">
                            <div className="p-3 rounded-xl bg-violet-100 dark:bg-violet-900/30">
                                <LayoutTemplate className="h-6 w-6 text-violet-500" />
                            </div>
                            <div>
                                <CardTitle className="text-xl">{t("agentsPage.templateTitle")}</CardTitle>
                                <CardDescription>{t("agentsPage.templateDesc")}</CardDescription>
                            </div>
                        </div>
                    </CardHeader>
                    <CardContent className="space-y-4">
                        <p className="text-sm text-muted-foreground">
                            {t("agentsPage.templateBody")}
                        </p>
                        <ul className="text-sm space-y-2">
                            <li className="flex items-center gap-2">
                                <span className="w-1.5 h-1.5 rounded-full bg-violet-500" />
                                {t("agentsPage.templatePoint1")}
                            </li>
                            <li className="flex items-center gap-2">
                                <span className="w-1.5 h-1.5 rounded-full bg-violet-500" />
                                {t("agentsPage.templatePoint2")}
                            </li>
                            <li className="flex items-center gap-2">
                                <span className="w-1.5 h-1.5 rounded-full bg-violet-500" />
                                {t("agentsPage.templatePoint3")}
                            </li>
                        </ul>
                        <Button variant="ghost" className="w-full group-hover:bg-violet-50 dark:group-hover:bg-violet-900/20">
                            {t("agentsPage.templateAction")}
                            <ArrowRight className="ml-2 h-4 w-4" />
                        </Button>
                    </CardContent>
                </Card>
            </div>
        </div>
    );
}
