from django import forms

from .models import Candidate
from .services import MAX_RESUME_BYTES

PDF_MAGIC = b'%PDF-'


class ApplicationForm(forms.Form):
    """The public /apply/<token>/ form. Mirrors the fields the old Google Form
    collected (see CLAUDE.md), minus "paste a Drive link" — resume is now a
    direct upload, validated below rather than trusted from a URL.
    """
    full_name = forms.CharField(
        max_length=200, label="Full name",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Jane Doe'}),
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'you@example.com'}),
    )
    years_experience = forms.ChoiceField(
        choices=Candidate.EXPERIENCE_CHOICES, label="Years of experience",
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    why_fit = forms.CharField(
        label="Why are you a fit for this role?",
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 5}),
    )
    resume = forms.FileField(
        label="Resume (PDF, max 5 MB)",
        widget=forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.pdf,application/pdf'}),
    )
    linkedin_url = forms.URLField(
        required=False, label="LinkedIn URL (optional)",
        widget=forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://linkedin.com/in/…'}),
    )
    consent = forms.BooleanField(
        required=True,
        label="I agree to my data being handled as described above.",
        widget=forms.CheckboxInput(attrs={'class': 'fancy-check'}),
    )

    def clean_resume(self):
        uploaded = self.cleaned_data['resume']

        if uploaded.size > MAX_RESUME_BYTES:
            raise forms.ValidationError(
                f"Resume must be smaller than {MAX_RESUME_BYTES // (1024 * 1024)} MB."
            )
        if not uploaded.name.lower().endswith('.pdf'):
            raise forms.ValidationError("Resume must be a PDF file.")

        # Extension alone is trivially spoofed — a browser or attacker can
        # rename any file to .pdf. Check the actual file signature too.
        head = uploaded.read(len(PDF_MAGIC))
        uploaded.seek(0)
        if head != PDF_MAGIC:
            raise forms.ValidationError("That file doesn't look like a valid PDF.")

        return uploaded
