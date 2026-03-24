// components/run-timeline/collapsible-details.tsx
import { useState } from "react";
import { ChevronDown, ChevronRight, Code2, FileText } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

interface CollapsibleDetailsProps {
    content: string;
    type: "json" | "text";
    status?: string;
}

export function CollapsibleDetails({ content, type, status }: CollapsibleDetailsProps) {
    const [isOpen, setIsOpen] = useState(false);

    // 如果内容很短，直接显示，不需要折叠
    const isShort = content.length < 50 && !content.includes('\n');

    if (isShort) {
        return (
            <div className="text-xs text-slate-400 font-mono bg-slate-950/50 px-2 py-1 rounded border border-slate-800/50 inline-block">
                {content}
            </div>
        );
    }

    return (
        <div className="w-full">
            <Button
                variant="ghost"
                size="sm"
                onClick={() => setIsOpen(!isOpen)}
                className={cn(
                    "h-6 px-0 text-xs font-normal hover:bg-transparent hover:text-blue-400 transition-colors flex items-center gap-1",
                    status === "running" ? "text-blue-400/70" : "text-slate-500"
                )}
            >
                {isOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                {isOpen ? "Hide" : "View"} {type === "json" ? "Payload" : "Output"}
                {type === "json" ? <Code2 className="h-3 w-3 ml-1 opacity-50" /> : <FileText className="h-3 w-3 ml-1 opacity-50" />}
            </Button>

            {isOpen && (
                <div className="mt-2 relative w-full grid grid-cols-1 min-w-0 overflow-hidden">
                    <div className="absolute left-0 top-0 bottom-0 w-0.5 bg-slate-800" />
                    <pre className="ml-3 overflow-x-auto rounded-md bg-slate-950 p-3 text-[10px] leading-relaxed font-mono text-slate-300 border border-slate-800/50 max-h-[300px] w-full min-w-0 custom-scrollbar block">
                        {content}
                    </pre>
                </div>
            )}
        </div>
    );
}