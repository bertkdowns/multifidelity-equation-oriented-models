"""A genuine time-domain plant response, not fixed temperatures on a time grid."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

HERE=Path(__file__).resolve().parents[1]


def test_aggregate_power_step_accumulates_heat_with_initial_conditions_only(solver, tmp_path):
    prefix=tmp_path/'step'
    completed=subprocess.run(
        [sys.executable,str(HERE/'examples/steam_generating_heat_pump_system/run_thermal_dynamics.py'),
         '--nfe','5','--prefix',str(prefix)],cwd=HERE,
        env={**os.environ,'OPENBLAS_NUM_THREADS':'1'},capture_output=True,text=True,timeout=120)
    assert completed.returncode==0,completed.stdout[-4000:]+completed.stderr[-2000:]
    report=json.loads(Path(str(prefix)+'_report.json').read_text())
    result=json.loads(Path(str(prefix)+'_results.json').read_text())
    assert report['solved'] and report['max_scaled_violation']<1e-6
    assert not any(report['structure'].values())
    variables={r['variable_path']:r['entries'] for r in result['variables']}
    def values(path):
        return {e['index'][0]:e['value'] for e in variables[path]}
    for alias in ['source_tank','warm_tank','hot_tank']:
        for field in ['mass','energy']:
            entries=variables[f'{alias}.inventory.{field}']
            assert entries[0]['fixed'] and all(not e['fixed'] for e in entries[1:])
        assert all(not e['fixed'] for e in variables[f'{alias}.inventory.temperature'])
        assert values(f'{alias}.inventory.level')[0]==pytest.approx(.1,abs=1e-8)
        m=values(f'{alias}.inventory.mass')
        assert max(m.values())-min(m.values())<1e-6
    temperature=values('source_tank.inventory.temperature')
    assert temperature[120]==pytest.approx(temperature[0],abs=1e-7)
    assert temperature[600]>temperature[120]+6
    for alias in ['warm_tank','hot_tank']:
        t=values(f'{alias}.inventory.temperature')
        assert t[600]==pytest.approx(t[0],abs=1e-7)
    power=values('phnix.performance.electrical_power')
    assert power[120]==pytest.approx(power[0])
    assert power[240]==pytest.approx(1.1*power[0])
    energy=values('source_tank.inventory.energy')
    # PHNIX COP is 2; tank heat gain must equal the extra sink heat over the
    # 480 s after the step, with only a small change in source-pump dissipation.
    expected=2*(power[240]-power[0])*(600-120)
    assert energy[600]-energy[0]==pytest.approx(expected,rel=1e-3)
    steam=values('steam_outlet.flow')
    assert steam[600]==pytest.approx(steam[0],rel=1e-8)


def test_detailed_relationship_turns_source_warming_into_extra_steam(solver, tmp_path):
    prefix=tmp_path/'cycle'
    completed=subprocess.run(
        [sys.executable,str(HERE/'examples/steam_generating_heat_pump_system/run_thermal_dynamics.py'),
         '--sghp','cycle','--nfe','5','--prefix',str(prefix)],cwd=HERE,
        env={**os.environ,'OPENBLAS_NUM_THREADS':'1'},capture_output=True,text=True,timeout=120)
    assert completed.returncode==0,completed.stdout[-4000:]+completed.stderr[-2000:]
    report=json.loads(Path(str(prefix)+'_report.json').read_text())
    result=json.loads(Path(str(prefix)+'_results.json').read_text())
    spec=json.loads(Path(str(prefix)+'_specification.json').read_text())
    assert report['solved'] and report['max_scaled_violation']<1e-6
    assert not any(report['structure'].values())
    assert result['model_id']=='steam_generating_heat_pump_system_thermal'
    assert result['implementation']['submodels']['sghp']['relationship']=='cycle'
    assert 'thermal_sghp_cop' not in spec['specifications']
    assert 'thermal_sghp_pressure_rise' in spec['specifications']
    variables={r['variable_path']:r['entries'] for r in result['variables']}
    def values(path):
        return {e['index'][0]:e['value'] for e in variables[path]}
    cop=values('sghp.performance.cop')
    steam=values('steam_outlet.flow')
    source=values('source_tank.inventory.temperature')
    assert cop[600]>cop[0]+.1
    assert steam[600]>steam[0]+3/3600
    assert source[120]==pytest.approx(source[0],abs=1e-7)
    assert source[600]>source[0]
    assert values('sghp.compressor.inlet_state.properties.vapor_fraction')[600]==pytest.approx(1)
    mass=values('hot_tank.inventory.mass')
    assert mass[600]<mass[0]
    source_mass=values('source_tank.inventory.mass')
    assert source_mass[600]==pytest.approx(source_mass[0],abs=1e-7)
    # Extra exported steam must be supplied by inventory, not by silently
    # increasing the fixed makeup flow or fixing mass at all time points.
    times=sorted(mass)
    makeup=values('makeup_state.state.flow')
    expected=sum((t-p)*(makeup[t]-steam[t]) for p,t in zip(times,times[1:]))
    total_change=sum(values(a+'.inventory.mass')[600]-values(a+'.inventory.mass')[0]
                     for a in ['source_tank','warm_tank','hot_tank'])
    assert total_change==pytest.approx(expected,abs=1e-6)
    for alias in ['source_tank','warm_tank','hot_tank']:
        for field in ['mass','energy']:
            entries=variables[f'{alias}.inventory.{field}']
            assert entries[0]['fixed'] and all(not e['fixed'] for e in entries[1:])
