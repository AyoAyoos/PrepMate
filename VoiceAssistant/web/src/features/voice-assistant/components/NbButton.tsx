import type { ButtonHTMLAttributes, ReactNode } from "react";

import styles from "./NbButton.module.css";

export type NbButtonVariant = "primary" | "danger" | "neutral" | "lilac";

export interface NbButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant: NbButtonVariant;
  children: ReactNode;
}

const variantClass: Record<NbButtonVariant, string> = {
  primary: styles.primary,
  danger: styles.danger,
  neutral: styles.neutral,
  lilac: styles.lilac,
};

export default function NbButton({
  variant,
  children,
  className = "",
  type = "button",
  ...props
}: NbButtonProps) {
  return (
    <button
      type={type}
      className={`${styles.button} ${variantClass[variant]} ${className}`.trim()}
      {...props}
    >
      {children}
    </button>
  );
}
