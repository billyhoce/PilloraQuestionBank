import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SchoolCombobox from './SchoolCombobox'
import { closestSchools } from './schoolSuggestions'

const SCHOOLS = [
  { id: 1, name: 'Anderson Secondary School' },
  { id: 2, name: "Raffles Girls' School" },
  { id: 3, name: 'Raffles Institution' },
  { id: 4, name: 'Crescent Girls School' },
]

const optionNames = () => within(screen.getByRole('listbox')).getAllByRole('option').map(o => o.textContent)

describe('closestSchools', () => {
  it('ranks the schools by how close their name is to the one read', () => {
    expect(closestSchools('Raffles Instn', SCHOOLS).map(s => s.id).slice(0, 2)).toEqual([3, 2])
  })

  it('keeps every school', () => {
    expect(closestSchools('zzz', SCHOOLS)).toHaveLength(4)
  })
})

describe('SchoolCombobox', () => {
  it('shows the chosen school and searches by typing', async () => {
    const onChange = vi.fn()
    render(<SchoolCombobox schools={SCHOOLS} value={4} onChange={onChange} />)
    const input = screen.getByRole('combobox', { name: 'School' })
    expect(input).toHaveValue('Crescent Girls School')
    await userEvent.clear(input)
    await userEvent.type(input, 'raff')
    expect(optionNames()).toEqual(["Raffles Girls' School", 'Raffles Institution'])
    await userEvent.click(screen.getByRole('option', { name: 'Raffles Institution' }))
    expect(onChange).toHaveBeenCalledWith(3)
  })

  it('shows an unresolved name in amber, with the closest schools suggested first', async () => {
    render(<SchoolCombobox schools={SCHOOLS} value={null} onChange={() => {}} extractedName="Raffles Instn" />)
    expect(screen.getByText(/not in the list/)).toHaveTextContent('Raffles Instn — not in the list')
    await userEvent.click(screen.getByRole('combobox', { name: 'School' }))
    expect(optionNames().slice(0, 2)).toEqual(['Raffles Institution', "Raffles Girls' School"])
  })

  it('says nothing about the name read once a school is chosen', () => {
    render(<SchoolCombobox schools={SCHOOLS} value={3} onChange={() => {}} extractedName="Raffles Instn" />)
    expect(screen.queryByText(/not in the list/)).not.toBeInTheDocument()
  })

  it('clearing the text clears the school', async () => {
    const onChange = vi.fn()
    render(<SchoolCombobox schools={SCHOOLS} value={3} onChange={onChange} />)
    await userEvent.clear(screen.getByRole('combobox', { name: 'School' }))
    expect(onChange).toHaveBeenCalledWith(null)
  })

  it('offers the typed text as a new school, last', async () => {
    const onNewSchool = vi.fn()
    render(<SchoolCombobox schools={SCHOOLS} value={null} onChange={() => {}} onNewSchool={onNewSchool} />)
    await userEvent.type(screen.getByRole('combobox', { name: 'School' }), 'Raffles Instn')
    expect(optionNames().at(-1)).toBe('Use “Raffles Instn” as a new school')
    await userEvent.click(screen.getByRole('option', { name: 'Use “Raffles Instn” as a new school' }))
    expect(onNewSchool).toHaveBeenCalledWith('Raffles Instn')
  })

  it('typing an existing name in any case offers that school, not a new one', async () => {
    const onChange = vi.fn()
    render(<SchoolCombobox schools={SCHOOLS} value={null} onChange={onChange} onNewSchool={() => {}} />)
    await userEvent.type(screen.getByRole('combobox', { name: 'School' }), 'raffles institution{Enter}')
    expect(onChange).toHaveBeenCalledWith(3)
  })

  it('shows a new school as chosen, marked new, and with no unresolved warning', () => {
    render(<SchoolCombobox schools={SCHOOLS} value={null} onChange={() => {}} onNewSchool={() => {}}
      newName="Raffles Instn" extractedName="Raffles Instn" />)
    expect(screen.getByRole('combobox', { name: 'School' })).toHaveValue('Raffles Instn')
    expect(screen.getByText(/New school/)).toHaveTextContent('New school — created when you confirm')
    expect(screen.queryByText(/not in the list/)).not.toBeInTheDocument()
  })
})
