import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from scipy.stats import linregress

DATA = Path("data")
SUMMARY = DATA / "Numisheet 2020 Uniaxial Tension Test Summary Table-PUBLISHED.csv"
GAUGE = 50.0    # mm, length of the virtual extensometer built from DIC points
HANDBOOK_E = {"BM1-DP980": 200e3, "BM1-AA6xxx-T4": 69e3}   # MPa, typical textbook values


def load_test(path, thickness, width):
    """Read one NIST test: stress from the load cell, strain from a DIC virtual extensometer."""
    df = pd.read_csv(path)
    dic = df.iloc[:, :-11].to_numpy()       # DIC columns come in groups of 6 per tracked point
    y = dic[:, 1::6]                        # Y position (mm) of each point in every frame
    i_bot = np.argmin(np.abs(y[0] + GAUGE / 2))
    i_top = np.argmin(np.abs(y[0] - GAUGE / 2))
    length = y[:, i_top] - y[:, i_bot]
    strain = length / length[0] - 1                                    # engineering strain
    stress = df["Force_(kN)"].to_numpy() * 1000 / (thickness * width)  # engineering stress, MPa
    return strain, stress


def analyse(strain, stress):
    """Extract E, 0.2% proof stress, UTS and elongations from a stress-strain curve."""
    i_uts = stress.argmax()
    uts = stress[i_uts]

    # Young's modulus: straight-line fit to the elastic region (10-40% of UTS, before max load)
    s, e = stress[:i_uts], strain[:i_uts]
    mask = (s > 0.1 * uts) & (s < 0.4 * uts)
    fit = linregress(e[mask], s[mask])
    E = fit.slope

    # 0.2% proof stress: where the curve crosses a line of slope E offset by 0.2% strain
    offset = stress - E * (strain - 0.002)
    i = np.argmax((strain > 0.002) & (offset < 0))
    f = offset[i - 1] / (offset[i - 1] - offset[i])
    proof = stress[i - 1] + f * (stress[i] - stress[i - 1])

    return {
        "E": E, "E_err": fit.stderr, "intercept": fit.intercept, "proof": proof, "uts": uts,
        "uniform_el": 100 * strain[i_uts],                       # strain at max load (%)
        "total_el": 100 * (strain[-1] - stress[-1] / E),         # plastic strain at end of test (%)
    }


if __name__ == "__main__":
    summary = pd.read_csv(SUMMARY, encoding="utf-8-sig")
    rows, curves = [], {}

    for _, test in summary.iterrows():
        path = DATA / f"{test['File Name']}.csv"
        if not path.exists():
            continue                        # only analyse the tests we've downloaded
        strain, stress = load_test(path, test["Thickness (mm)"], test["Width (mm)"])
        r = analyse(strain, stress)
        name = test["Material"]
        curves.setdefault(name, []).append((test["Repeat Number"], strain, stress, r))
        rows.append({"material": name, "angle": test["Angle from RD (deg)"], "repeat": test["Repeat Number"],
                     "E_GPa": r["E"] / 1000, "E_err_GPa": r["E_err"] / 1000, "proof_MPa": r["proof"],
                     "uts_MPa": r["uts"], "uniform_el_pct": r["uniform_el"], "total_el_pct": r["total_el"]})

    results = pd.DataFrame(rows)
    results.to_csv("results.csv", index=False)
    pd.set_option("display.width", 140)
    print(results.round(2).to_string(index=False))

    print("\nYoung's modulus vs typical handbook value:")
    for name, group in results.groupby("material"):
        ref = HANDBOOK_E[name] / 1000
        diff = 100 * (group["E_GPa"] - ref) / ref
        print(f"  {name}: mean {group['E_GPa'].mean():.1f} GPa vs {ref:.0f} GPa "
              f"({len(group)} test(s), max difference {diff.abs().max():.1f}%)")

    # Plots: full curves on top, elastic region and 0.2% offset underneath
    fig, axes = plt.subplots(2, len(curves), figsize=(6 * len(curves), 9), squeeze=False)
    for col, (name, tests) in enumerate(curves.items()):
        top, bottom = axes[0, col], axes[1, col]
        for repeat, strain, stress, r in tests:
            line, = top.plot(100 * strain, stress, label=f"Repeat {repeat}")
            top.plot(100 * strain[stress.argmax()], r["uts"], "s", color=line.get_color())
            bottom.plot(100 * strain, stress, ".", markersize=3, color=line.get_color(), label=f"Repeat {repeat} data")
            proof_strain = r["proof"] / r["E"] + 0.002
            el = np.linspace(0, 0.8 * r["proof"] / r["E"], 20)
            bottom.plot(100 * el, r["E"] * el + r["intercept"], "-", color=line.get_color(),
                        label=f"E = {r['E']/1000:.1f} GPa")
            off = np.linspace(0.002, proof_strain + 0.001, 20)
            bottom.plot(100 * off, r["E"] * (off - 0.002), "--", color=line.get_color())
            bottom.plot(100 * proof_strain, r["proof"], "o", color=line.get_color(),
                        label=f"0.2% proof = {r['proof']:.0f} MPa")
        r0 = tests[0][3]
        top.set_title(f"{name}: engineering stress-strain (NIST data)")
        bottom.set_title(f"{name}: elastic fit and 0.2% offset")
        bottom.set_xlim(0, 200 * (r0["proof"] / r0["E"] + 0.002))
        bottom.set_ylim(0, 1.25 * r0["proof"])
        for ax in (top, bottom):
            ax.set_xlabel("Engineering strain (%)")
            ax.set_ylabel("Engineering stress (MPa)")
            ax.grid(True, alpha=0.3)
            ax.legend(fontsize=8)

    Path("figures").mkdir(exist_ok=True)
    fig.tight_layout()
    fig.savefig("figures/tensile_analysis.png", dpi=150)
    plt.show()