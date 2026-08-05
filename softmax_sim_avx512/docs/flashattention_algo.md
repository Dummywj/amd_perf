**Require:** Matrices $\mathbf Q,\mathbf K,\mathbf V\in\mathbb{R}^{N\times d}$ in HBM, on-chip SRAM of size $M$.

1: Set block sizes $B_c=\left\lceil\frac{M}{4d}\right\rceil$, $B_r=\min\left(\left\lceil\frac{M}{4d}\right\rceil,d\right)$.

2: Initialize $\mathbf O=(0)_{N\times d}\in\mathbb{R}^{N\times d}$, $\ell=(0)_N\in\mathbb{R}^N$, $m=(-\infty)_N\in\mathbb{R}^N$ in HBM.

3: Divide $\mathbf Q$ into $T_r=\left\lceil\frac{N}{B_r}\right\rceil$ blocks $\mathbf Q_1,\ldots,\mathbf Q_{T_r}$ of size $B_r\times d$ each, and divide $\mathbf K,\mathbf V$ into $T_c=\left\lceil\frac{N}{B_c}\right\rceil$ blocks $\mathbf K_1,\ldots,\mathbf K_{T_c}$ and $\mathbf V_1,\ldots,\mathbf V_{T_c}$, of size $B_c\times d$ each.

4: Divide $\mathbf O$ into $T_r$ blocks $\mathbf O_1,\ldots,\mathbf O_{T_r}$ of size $B_r\times d$ each, divide $\ell$ into $T_r$ blocks $\ell_1,\ldots,\ell_{T_r}$ of size $B_r$ each, divide $m$ into $T_r$ blocks $m_1,\ldots,m_{T_r}$ of size $B_r$ each.

5: **for** $1\le j\le T_c$ **do**

6: Load $\mathbf K_j,\mathbf V_j$ from HBM to on-chip SRAM.

7: **for** $1\le i\le T_r$ **do**

8: Load $\mathbf Q_i,\mathbf O_i,\ell_i,m_i$ from HBM to on-chip SRAM.

9: On chip, compute $\mathbf S_{ij}=\mathbf Q_i\mathbf K_j^\top\in\mathbb{R}^{B_r\times B_c}$.

10: On chip, compute $\widetilde m_{ij}=\operatorname{rowmax}(\mathbf S_{ij})\in\mathbb{R}^{B_r}$, $\widetilde{\mathbf P}_{ij}=\exp(\mathbf S_{ij}-\widetilde m_{ij})\in\mathbb{R}^{B_r\times B_c}$ (pointwise), $\widetilde\ell_{ij}=\operatorname{rowsum}(\widetilde{\mathbf P}_{ij})\in\mathbb{R}^{B_r}$.

11: On chip, compute $m_i^{\mathrm{new}}=\max(m_i,\widetilde m_{ij})\in\mathbb{R}^{B_r}$, $\ell_i^{\mathrm{new}}=e^{m_i-m_i^{\mathrm{new}}}\ell_i+e^{\widetilde m_{ij}-m_i^{\mathrm{new}}}\widetilde\ell_{ij}\in\mathbb{R}^{B_r}$.

12: Write $\mathbf O_i\leftarrow\operatorname{diag}(\ell_i^{\mathrm{new}})^{-1}\left(\operatorname{diag}(\ell_i)e^{m_i-m_i^{\mathrm{new}}}\mathbf O_i+e^{\widetilde m_{ij}-m_i^{\mathrm{new}}}\widetilde{\mathbf P}_{ij}\mathbf V_j\right)$ to HBM.

13: Write $\ell_i\leftarrow\ell_i^{\mathrm{new}}$, $m_i\leftarrow m_i^{\mathrm{new}}$ to HBM.

14: **end for**

15: **end for**

16: Return $\mathbf O$.