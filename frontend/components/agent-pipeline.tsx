"use client";

import { cn } from "@/lib/utils";
import { CheckCircle2, Circle, Activity, AlertCircle, Sparkles } from "lucide-react";
import { LazyMotion, m, domAnimation, AnimatePresence } from "framer-motion";

export interface PipelineStep {
    id: string;
    name: string;
    description: string;
    status: "pending" | "running" | "completed" | "failed";
}

interface AgentPipelineProps {
    steps: PipelineStep[];
}

export function AgentPipeline({ steps }: AgentPipelineProps) {
    return (
        <LazyMotion features={domAnimation}>
            <div className="flex items-center justify-between w-full max-w-5xl mx-auto py-10 px-6 relative">
                {/* Background decorative line */}
                <div className="absolute top-[calc(50%-1px)] left-12 right-12 h-[2px] bg-zinc-800/50 z-0" />

                {steps.map((step, index) => (
                    <div key={step.id} className="flex items-center flex-1 last:flex-none relative z-10">
                        <div className="flex flex-col items-center group">
                            {/* Step Circle with Glow and Animation */}
                            <div className="relative">
                                <AnimatePresence mode="wait">
                                    {step.status === "running" && (
                                        <m.div
                                            initial={{ opacity: 0, scale: 0.95 }}
                                            animate={{ opacity: 1, scale: 1.2 }}
                                            exit={{ opacity: 0, scale: 0.95 }}
                                            className="absolute inset-0 rounded-full bg-blue-500/20 blur-xl"
                                        />
                                    )}
                                </AnimatePresence>

                                <m.div
                                    className={cn(
                                        "size-12 rounded-full border-2 flex items-center justify-center transition-all duration-500 bg-background/80 backdrop-blur-sm relative overflow-hidden",
                                        step.status === "completed" && "border-emerald-500 text-emerald-500 shadow-[0_0_15px_rgba(16,185,129,0.2)]",
                                        step.status === "running" && "border-blue-400 text-blue-400 shadow-[0_0_20px_rgba(96,165,250,0.4)] ring-4 ring-blue-500/10",
                                        step.status === "pending" && "border-zinc-800 text-zinc-600",
                                        step.status === "failed" && "border-rose-500 text-rose-500"
                                    )}
                                    whileHover={{ scale: 1.05 }}
                                    transition={{ type: "spring", stiffness: 300, damping: 20 }}
                                >
                                    {step.status === "completed" && (
                                        <m.div initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}>
                                            <CheckCircle2 className="size-6" />
                                        </m.div>
                                    )}
                                    {step.status === "running" && (
                                        <div className="relative flex items-center justify-center">
                                            <Activity className="size-6 animate-pulse" />
                                            <m.div
                                                className="absolute -top-1 -right-1"
                                                animate={{ rotate: 360 }}
                                                transition={{ duration: 4, repeat: Infinity, ease: "linear" }}
                                            >
                                                <Sparkles className="size-3 text-blue-300" />
                                            </m.div>
                                        </div>
                                    )}
                                    {step.status === "failed" && <AlertCircle className="size-6" />}
                                    {step.status === "pending" && <Circle className="size-4 fill-current opacity-20" />}

                                    {/* Inner gradient overlay for active steps */}
                                    {step.status === "running" && (
                                        <div className="absolute inset-0 bg-gradient-to-tr from-blue-500/10 to-transparent pointer-events-none" />
                                    )}
                                </m.div>
                            </div>

                            {/* Label with better typography */}
                            <div className="absolute top-16 left-1/2 -translate-x-1/2 text-center w-32">
                                <p className={cn(
                                    "text-[11px] font-bold uppercase tracking-[0.1em] transition-colors duration-300",
                                    step.status === "running" ? "text-blue-400" :
                                        step.status === "completed" ? "text-emerald-400" :
                                            "text-zinc-500"
                                )}>
                                    {step.name}
                                </p>
                                <p className="text-[10px] text-zinc-500 hidden sm:block opacity-0 group-hover:opacity-100 transition-opacity duration-300 mt-1 line-clamp-2 leading-tight px-1">
                                    {step.description}
                                </p>
                            </div>
                        </div>

                        {/* Connecting Line with Gradient Progress */}
                        {index < steps.length - 1 && (
                            <div className="flex-1 h-[3px] mx-2 bg-zinc-800/40 rounded-full relative overflow-hidden min-w-[30px]">
                                <m.div
                                    className={cn(
                                        "absolute inset-0 origin-left",
                                        step.status === "completed" ? "bg-gradient-to-r from-emerald-500 to-emerald-400" : "bg-blue-500/30"
                                    )}
                                    initial={{ scaleX: 0 }}
                                    animate={{ scaleX: step.status === "completed" ? 1 : (step.status === "running" ? 0.5 : 0) }}
                                    transition={{ duration: 1, ease: "circOut" }}
                                />
                                {step.status === "running" && (
                                    <m.div
                                        className="absolute inset-0 bg-gradient-to-r from-transparent via-blue-400/30 to-transparent"
                                        animate={{ x: ['-100%', '100%'] }}
                                        transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
                                    />
                                )}
                            </div>
                        )}
                    </div>
                ))}
            </div>
        </LazyMotion>
    );
}
