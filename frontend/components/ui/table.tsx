import { cn } from "@/lib/utils"

interface TableProps extends React.HTMLAttributes<HTMLTableElement> {
    ref?: React.Ref<HTMLTableElement>
}
function Table({ className, ref, ...props }: TableProps) {
    return (
        <div className="relative w-full overflow-auto">
            <table
                ref={ref}
                className={cn("w-full caption-bottom text-sm", className)}
                {...props}
            />
        </div>
    )
}

interface TableHeaderProps extends React.HTMLAttributes<HTMLTableSectionElement> {
    ref?: React.Ref<HTMLTableSectionElement>
}
function TableHeader({ className, ref, ...props }: TableHeaderProps) {
    return <thead ref={ref} className={cn("[&_tr]:border-b", className)} {...props} />
}

interface TableBodyProps extends React.HTMLAttributes<HTMLTableSectionElement> {
    ref?: React.Ref<HTMLTableSectionElement>
}
function TableBody({ className, ref, ...props }: TableBodyProps) {
    return (
        <tbody
            ref={ref}
            className={cn("[&_tr:last-child]:border-0", className)}
            {...props}
        />
    )
}

interface TableFooterProps extends React.HTMLAttributes<HTMLTableSectionElement> {
    ref?: React.Ref<HTMLTableSectionElement>
}
function TableFooter({ className, ref, ...props }: TableFooterProps) {
    return (
        <tfoot
            ref={ref}
            className={cn(
                "border-t bg-muted/50 font-medium [&>tr]:last:border-b-0",
                className
            )}
            {...props}
        />
    )
}

interface TableRowProps extends React.HTMLAttributes<HTMLTableRowElement> {
    ref?: React.Ref<HTMLTableRowElement>
}
function TableRow({ className, ref, ...props }: TableRowProps) {
    return (
        <tr
            ref={ref}
            className={cn(
                "border-b transition-colors hover:bg-muted/50 data-[state=selected]:bg-muted",
                className
            )}
            {...props}
        />
    )
}

interface TableHeadProps extends React.ThHTMLAttributes<HTMLTableCellElement> {
    ref?: React.Ref<HTMLTableCellElement>
}
function TableHead({ className, ref, ...props }: TableHeadProps) {
    return (
        <th
            ref={ref}
            className={cn(
                "h-12 px-4 text-left align-middle font-medium text-muted-foreground [&:has([role=checkbox])]:pr-0",
                className
            )}
            {...props}
        />
    )
}

interface TableCellProps extends React.TdHTMLAttributes<HTMLTableCellElement> {
    ref?: React.Ref<HTMLTableCellElement>
}
function TableCell({ className, ref, ...props }: TableCellProps) {
    return (
        <td
            ref={ref}
            className={cn("p-4 align-middle [&:has([role=checkbox])]:pr-0", className)}
            {...props}
        />
    )
}

interface TableCaptionProps extends React.HTMLAttributes<HTMLTableCaptionElement> {
    ref?: React.Ref<HTMLTableCaptionElement>
}
function TableCaption({ className, ref, ...props }: TableCaptionProps) {
    return (
        <caption
            ref={ref}
            className={cn("mt-4 text-sm text-muted-foreground", className)}
            {...props}
        />
    )
}

export {
    Table,
    TableHeader,
    TableBody,
    TableFooter,
    TableHead,
    TableRow,
    TableCell,
    TableCaption,
}
