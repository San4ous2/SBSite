from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import logging
import re
import stripe

# PDF Generation
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from io import BytesIO
from reportlab.lib.fonts import addMapping
import os # To handle paths correctly


# Google AI
from google import genai
from django.conf import settings

logger = logging.getLogger(__name__)

# API Keys
API_KEY = os.environ.get('GOOGLE_API_KEY')
stripe.api_key = settings.STRIPE_SECRET_KEY

# ============= FONTU REĢISTRĀCIJA =============
FONT_DIR = os.path.join(settings.BASE_DIR, 'fonts')
NORMAL_FONT = os.path.join(FONT_DIR, 'DejaVuSans.ttf')
BOLD_FONT = os.path.join(FONT_DIR, 'DejaVuSans-Bold.ttf')

# Pārbaude, vai faili eksistē (lai izvairītos no slēptām kļūdām)
if not os.path.exists(NORMAL_FONT):
    print(f"❌ KĻŪDA: Fails nav atrasts: {NORMAL_FONT}")
if not os.path.exists(BOLD_FONT):
    print(f"❌ KĻŪDA: Fails nav atrasts: {BOLD_FONT}")

try:
    # Reģistrējam fontus ar identiskiem nosaukumiem kā stilos
    pdfmetrics.registerFont(TTFont('DejaVuSans', NORMAL_FONT))
    pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', BOLD_FONT))

    # Reģistrējam "ģimeni", lai ReportLab saprastu saistību starp parasto un treknrakstu
    addMapping('DejaVuSans', 0, 0, 'DejaVuSans')  # Normal
    addMapping('DejaVuSans', 1, 0, 'DejaVuSans-Bold')  # Bold

    print("✅ Fonti veiksmīgi piereģistrēti!")
except Exception as e:
    print(f"❌ KRITISKA KĻŪDA FONTU REĢISTRĀCIJĀ: {e}")
    logger.error(f"Font registration failed: {e}")


def clean_text(text):
    """Removes extra characters and formatting"""
    text = re.sub(r'\[.*?\]', '', text)
    text = text.replace('**', '').replace('* ', '').strip()
    return text


def home(request):
    return render(request, 'home.html', {
        'STRIPE_PUBLISHABLE_KEY': settings.STRIPE_PUBLISHABLE_KEY
    })


def basic_test_view(request):
    """Basic free test with 9 questions (max 12 points)"""
    if request.method == 'POST':
        try:
            # --- 1. DATA COLLECTION ---
            def get_f(name):
                val = request.POST.get(name, '0').replace(',', '.').strip()
                return float(val) if val else 0.0

            currency = request.POST.get('currency', 'EUR')
            age_group = request.POST.get('age_group', 'Nav norādīts')
            goal = request.POST.get('goal', 'Nav norādīts')

            # Income
            income = get_f('income') or 1.0
            inc_sources = [
                get_f('i_alga'),
                get_f('i_prem'),
                get_f('i_div'),
                get_f('i_proc'),
                get_f('i_crypto'),
                get_f('i_deposit'),
                get_f('i_social')
            ]

            # Loans
            has_loan = request.POST.get('has_loan') == 'ja'

            # Safety cushion
            has_safety_cushion = request.POST.get('has_safety_cushion') == 'ja'
            safety_cushion_amount = get_f('safety_cushion') if has_safety_cushion else 0

            # Investment plans
            will_inv = request.POST.get('will_inv')
            need_cons = request.POST.get('need_cons')

            # --- 2. SCORING LOGIC (BASIC VERSION - MAX 12 POINTS) ---
            score = 0

            # 1. Income structure (max 10 points)
            # According to document: if largest income source is 80-100% then 0-2 points, 60-80% then 3-5, 40-60% then 6-8, <40% then 10
            max_inc_source = max(inc_sources) if any(inc_sources) else income
            inc_div_pct = (max_inc_source / income) * 100

            if inc_div_pct >= 80:
                score += 2
            elif inc_div_pct >= 60:
                score += 4
            elif inc_div_pct >= 40:
                score += 7
            else:
                score += 10

            # 2. Loans (max 1 point)
            if not has_loan:
                score += 1

            # 3. Investment plans (max 1 point)
            if will_inv in ['ja', 'already']:
                score += 1

            # --- FINAL CALCULATION ---
            max_possible_points = 12
            final_percent = min(int((score / max_possible_points) * 100), 100)

            # Determine level - Updated according to document
            level_text = ""
            level_description = ""
            basic_tips = []

            if score <= 4:
                level_text = "Iesācēja līmenis"
                level_description = "Slikta finanšu situācija. Jums ir nepieciešams uzlabot savu finanšu pārvaldību."
                basic_tips = [
                    "Jāsāk mācīties pašus pamatus",
                    "Izveidojiet budžetu un sekojiet līdzi saviem izdevumiem",
                    "Sāciet veidot drošības spilvenu vismaz 3 mēnešu izdevumiem"
                ]
            elif score <= 8:
                level_text = "Vidējais līmenis"
                level_description = "Ir galveno bāzu zināšanu līmenis. Jums ir pamata izpratne par finanšu pārvaldību."
                basic_tips = [
                    "Jāmācās pamatzināšanas par finanšu instrumentiem",
                    "Diversificējiet savus ieņēmumu avotus",
                    "Sāciet investēt mazu summu regulāri"
                ]
            else:
                level_text = "Augstais līmenis"
                level_description = "Vidējā līmeņa finanšu situācija. Jums ir labas finanšu zināšanas un prakse."
                basic_tips = [
                    "Iedziļināties finanšu instrumentos",
                    "Palieliniet investīciju portfeli ar dažādiem instrumentiem",
                    "Apsveriet konsultāciju ar finanšu plānotāju"
                ]

            # Store data in session for PDF export
            request.session['basic_result'] = {
                'score': final_percent,
                'raw_score': score,
                'level_text': level_text,
                'level_description': level_description,
                'basic_tips': basic_tips,
                'currency': currency,
                'age_group': age_group,
                'goal': goal
            }

            return render(request, 'result_basic_updated.html', {
                'score': final_percent,
                'raw_score': score,
                'level_text': level_text,
                'level_description': level_description,
                'basic_tips': basic_tips,
                'STRIPE_PUBLISHABLE_KEY': settings.STRIPE_PUBLISHABLE_KEY
            })

        except Exception as e:
            logger.error(f"Basic test error: {e}")
            return render(request, 'test_basic.html', {'error': 'Notika kļūda aprēķinos'})

    return render(request, 'test_basic.html')


def test_view(request):
    """Extended test with 17 questions (max 65 points) + AI recommendations"""
    if request.method == 'POST':
        try:
            # --- 1. DATA COLLECTION ---
            def get_f(name):
                val = request.POST.get(name, '0').replace(',', '.').strip()
                return float(val) if val else 0.0

            currency = request.POST.get('currency', 'EUR')
            age_group = request.POST.get('age_group', 'Nav norādīts')
            goal = request.POST.get('goal', 'Nav norādīts')

            # Income
            income = get_f('income') or 1.0
            inc_sources = [
                get_f('i_alga'),
                get_f('i_prem'),
                get_f('i_div'),
                get_f('i_proc'),
                get_f('i_crypto'),
                get_f('i_deposit'),
                get_f('i_social')
            ]

            # Expenses
            expenses = get_f('expenses')
            exp_pnp = get_f('exp_pnp')
            exp_fun = get_f('exp_fun')
            exp_inv = get_f('exp_inv')

            # Investments
            inv_sources = [get_f('v_akc'), get_f('v_etf'), get_f('v_obl'), get_f('v_crypto')]
            total_invested_portfolio = sum(inv_sources)

            # History and forecasts
            avg_inc = get_f('avg_inc') or 1.0
            avg_exp = get_f('avg_exp')
            inc_trend = request.POST.get('inc_trend')
            exp_trend = request.POST.get('exp_trend')

            # Safety cushion
            has_safety_cushion = request.POST.get('has_safety_cushion') == 'ja'
            safety_cushion_amount = get_f('safety_cushion') if has_safety_cushion else 0

            # Loans
            has_loan = request.POST.get('has_loan') == 'ja'
            loan_type = request.POST.get('loan_type')

            # Plans and consultant
            will_inv = request.POST.get('will_inv')
            need_cons = request.POST.get('need_cons')

            # --- 2. SCORING LOGIC (FULL VERSION - MAX 65 POINTS) ---
            score = 0

            # 1. Income structure (max 10 points)
            # If largest income source is 80-100% then 0-2, 60-80% then 3-5, 40-60% then 6-8, <40% then 10
            max_inc_source = max(inc_sources) if any(inc_sources) else income
            inc_div_pct = (max_inc_source / income) * 100

            if inc_div_pct >= 80:
                score += 2
            elif inc_div_pct >= 60:
                score += 4
            elif inc_div_pct >= 40:
                score += 7
            else:
                score += 10

            # 2. Expense/Income ratio (max 10 points)
            # If 100%+ then 0, 80-100% then 1-4, 60-80% then 5-8, 50-60% then 8-9, <50% then 10
            ratio_cur = (expenses / income) * 100

            if ratio_cur > 100:
                score += 0
            elif ratio_cur >= 80:
                score += 2.5
            elif ratio_cur >= 60:
                score += 6.5
            elif ratio_cur >= 50:
                score += 8.5
            else:
                score += 10

            # 3. Expense structure (max 10 points)
            # If expenses are 80%+ of income: if pnp is 80-100% then 0-4, 60-80% then 5-8, <60% then 8+
            # Otherwise: based on pnp/fun/inv distribution
            exp_ratio = (expenses / income) * 100 if income > 0 else 100
            pnp_pct = (exp_pnp / expenses) * 100 if expenses > 0 else 0
            fun_pct_val = (exp_fun / expenses) * 100 if expenses > 0 else 0
            inv_pct = (exp_inv / expenses) * 100 if expenses > 0 else 0

            if exp_ratio >= 80:
                # High expense ratio scenario
                if pnp_pct >= 80:
                    score += 2
                elif pnp_pct >= 60:
                    score += 6
                else:
                    score += 9
            else:
                # Normal expense ratio scenario
                if pnp_pct >= 80 or fun_pct_val >= 80:
                    score += 1
                elif (pnp_pct >= 60 or fun_pct_val >= 60) and inv_pct < 20:
                    score += 3.5
                elif pnp_pct >= 60 or fun_pct_val >= 60:
                    score += 5.5
                elif (pnp_pct >= 40 or fun_pct_val >= 40) and inv_pct >= 20 and inv_pct < 40:
                    score += 7.5
                elif inv_pct >= 40 and inv_pct <= 60 and pnp_pct + fun_pct_val >= 40:
                    score += 8.5
                elif inv_pct > 60:
                    score += 10
                else:
                    score += 5

            # 4. Investment portfolio diversification (max 10 points)
            # If no investments then 0, if one investment type is 80-100% then 0-2, 60-80% then 3-5, 40-60% then 6-8, <40% then 10
            if total_invested_portfolio == 0:
                score += 0
            else:
                max_inv_source = max(inv_sources) if any(inv_sources) else total_invested_portfolio
                inv_concentration = (max_inv_source / total_invested_portfolio) * 100 if total_invested_portfolio > 0 else 100

                if inv_concentration >= 80:
                    score += 2
                elif inv_concentration >= 60:
                    score += 4
                elif inv_concentration >= 40:
                    score += 7
                else:
                    score += 10

            # 5. Historical income stability (max 5 points) - partial importance
            inc_stability = abs((income - avg_inc) / avg_inc) * 100 if avg_inc > 0 else 100

            if inc_stability <= 5:
                score += 5
            elif inc_stability <= 15:
                score += 3
            elif inc_stability <= 30:
                score += 1
            else:
                score += 0

            # 6. Historical expense stability (max 10 points)
            # Same scoring as expense/income ratio
            exp_stability = abs((expenses - avg_exp) / avg_exp) * 100 if avg_exp > 0 else 100

            if exp_stability > 100:
                score += 0
            elif exp_stability >= 80:
                score += 2.5
            elif exp_stability >= 60:
                score += 6.5
            elif exp_stability >= 50:
                score += 8.5
            else:
                score += 10

            # 7. Forecast trends (max 5 points)
            # Income increase: 1 point, Income decrease: 0 points
            # Expense decrease: 1 point, Expense increase: 0 points
            trend_score = 0
            if inc_trend == 'aug':
                trend_score += 1
            elif inc_trend == 'sta':
                trend_score += 0.5

            if exp_trend == 'maz':
                trend_score += 1
            elif exp_trend == 'sta':
                trend_score += 0.5

            # Scale to 5 points max
            score += trend_score * 2.5

            # 8. Loans (max 3 points)
            # If expenses are 60%+ of income: if has loans then 0, if no loans then 1
            # Otherwise: if has loans then 1, if no loans then 0
            if exp_ratio >= 60:
                if not has_loan:
                    score += 1
                else:
                    score += 0
            else:
                if has_loan:
                    score += 1
                else:
                    score += 2

            # 9. Loan type (max 1 point)
            # If short-term loans then 0, if long-term then 1
            if has_loan:
                if loan_type == 'ilg':
                    score += 1
                elif loan_type == 'ist':
                    score += 0
                else:
                    score += 0.5

            # 10. Investment plans (max 1 point)
            # If yes then 1, if no then 0, if already investing then 1
            if will_inv in ['ja', 'already']:
                score += 1

            # 11. Safety cushion (max 10 points)
            # If no then 0, if 1-2x monthly expenses then 1-2, 3-5x then 3-5, 6-8x then 6-8, 9-10x then 9-10
            if not has_safety_cushion or safety_cushion_amount == 0:
                score += 0
            else:
                safety_ratio = safety_cushion_amount / avg_exp if avg_exp > 0 else 0
                if safety_ratio >= 9:
                    score += 10
                elif safety_ratio >= 6:
                    score += 7
                elif safety_ratio >= 3:
                    score += 4
                elif safety_ratio >= 1:
                    score += 1.5
                else:
                    score += 0

            # --- AI RECOMMENDATIONS ---
            ai_tips = []
            try:
                client = genai.Client(api_key=API_KEY)

                prompt = f"""
LOMS: Tu esi profesionāls finanšu stratēģis. 
UZDEVUMS: Sniedz 5 personalizētus, padziļinātus ieteikumus latviešu valodā, balstoties uz datiem.

DATI ANALĪZEI:
- Ieņēmumi: {income} {currency}
- Izdevumi: {expenses} {currency}
- Investīcijas: {total_invested_portfolio} {currency}
- Parādi: {'Jā' if has_loan else 'Nē'}
- Mērķis: {goal}

INSTRUKCIJAS:
1. AIZLIEGTS rakstīt ievadu (piem. "Šeit ir ieteikumi...") vai nobeigumu.
2. KATRAM ieteikumam jābūt 2-3 teikumus garam.
3. PIRMAIS teikums: Identificē konkrētu problēmu vai iespēju datos.
4. OTRAIS teikums: Sniedz praktisku rīcības plānu.
5. NEIZMANTO numerāciju (1., 2.), neizmanto emocijzīmes (emojis).
6. Katru ieteikumu sāc jaunā rindā.

IZVADE TIKAI LATVIEŠU VALODĀ:
"""

                response = client.models.generate_content(
                    model='models/gemini-2.5-flash',
                    contents=prompt
                )

                tips_text = response.text.strip()
                tips_lines = [line.strip() for line in tips_text.split('\n') if line.strip()]
                ai_tips = [clean_text(tip) for tip in tips_lines if len(tip) > 10][:5]

            except Exception as e:
                logger.error(f"AI generation error: {e}")
                ai_tips = [
                    "Izveidojiet detalizētu budžetu un izsekojiet visus izdevumus",
                    "Veidojiet ārkārtas fondu 3-6 mēnešu izdevumiem",
                    "Sāciet regulāri investēt vismaz 10% no ienākumiem",
                    "Optimizējiet izdevumus - identificējiet un samaziniet nevajadzīgos tēriņus",
                    "Izglītojieties par personīgajām finansēm un investīcijām"
                ]

            # --- FINAL CALCULATION ---
            max_possible_points = 65
            final_percent = min(int((score / max_possible_points) * 100), 100)

            # Determine level - Updated according to document (0-10, 10-20, 20-30, 30-40, 40-50, 50-55, 55-65)
            if score >= 55:
                level_text = "Ideāla finanšu situācija"
            elif score >= 50:
                level_text = "Ļoti labs finanšu situācijas līmenis"
            elif score >= 40:
                level_text = "Laba finanšu situācija"
            elif score >= 30:
                level_text = "Virs vidējās finanšu situācijas līmenis"
            elif score >= 20:
                level_text = "Vidējā līmeņa finanšu situācija"
            elif score >= 10:
                level_text = "Ir galveno bāzu zināšanu līmenis"
            else:
                level_text = "Slikta finanšu situācija"


            request.session['pro_result'] = {
                'score': final_percent,
                'raw_score': score,
                'level_text': level_text,
                'tips': ai_tips,
                'income': income,
                'expenses': expenses,
                'currency': currency,
                'age_group': age_group,
                'goal': goal
            }

            return render(request, 'result_updated.html', {
                'score': final_percent,
                'raw_score': score,
                'level_text': level_text,
                'tips': ai_tips
            })

        except Exception as e:
            logger.error(f"Extended test error: {e}")
            return render(request, 'test.html', {'error': 'Notika kļūda aprēķinos'})

    return render(request, 'test.html')


# ============= PDF EXPORT FUNCTIONS =============

def export_pdf_basic(request):
    """Export basic test results to PDF with Latvian character support"""
    try:
        result = request.session.get('basic_result')
        if not result:
            return HttpResponse("Nav rezultātu. Lūdzu, vispirms nokārtojiet testu.", status=400)

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm)
        story = []
        styles = getSampleStyleSheet()

        # Create custom styles with Unicode font
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontName='DejaVuSans-Bold',
            fontSize=24,
            textColor=colors.HexColor('#1a335d'),
            spaceAfter=30,
            alignment=TA_CENTER
        )
        
        subtitle_style = ParagraphStyle(
            'CustomSubtitle',
            parent=styles['Normal'],
            fontName='DejaVuSans',
            fontSize=12,
            textColor=colors.HexColor('#64748b'),
            alignment=TA_CENTER,
            spaceAfter=20
        )
        
        normal_style = ParagraphStyle(
            'CustomNormal',
            parent=styles['Normal'],
            fontName='DejaVuSans',
            fontSize=11,
            leading=16
        )
        
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontName='DejaVuSans-Bold',
            fontSize=14,
            textColor=colors.HexColor('#1a335d'),
            spaceAfter=10,
            spaceBefore=20
        )

        # Title
        story.append(Paragraph("Finanšu Pratības Novērtējums", title_style))
        story.append(Paragraph("BEZMAKSAS VERSIJA", subtitle_style))
        story.append(Spacer(1, 20))

        # Score
        score_data = [
            ['Jūsu rezultāts:', f"{result['raw_score']}/12 punkti"],
            ['Procenti:', f"{result['score']}%"],
            ['Līmenis:', result['level_text']]
        ]
        score_table = Table(score_data, colWidths=[8 * cm, 8 * cm])
        score_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8f9fa')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#1a335d')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'DejaVuSans-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey)
        ]))
        story.append(score_table)
        story.append(Spacer(1, 20))

        # Description
        story.append(Paragraph(f"<b>Apraksts:</b> {result['level_description']}", normal_style))
        story.append(Spacer(1, 20))

        # Tips
        story.append(Paragraph("Pamata ieteikumi:", heading_style))
        for i, tip in enumerate(result['basic_tips'], 1):
            story.append(Paragraph(f"{i}. {tip}", normal_style))
            story.append(Spacer(1, 10))

        # Footer
        story.append(Spacer(1, 30))
        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontName='DejaVuSans',
            fontSize=9,
            textColor=colors.HexColor('#94a3b8'),
            alignment=TA_CENTER
        )
        story.append(Paragraph("Finanšu Pratība © 2025 | Personalizēts finanšu novērtējums", footer_style))

        doc.build(story)
        buffer.seek(0)

        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="finansu_pratiba_basic.pdf"'
        return response

    except Exception as e:
        logger.error(f"PDF export error (basic): {e}")
        return HttpResponse(f"Kļūda PDF izveidē: {str(e)}", status=500)


def export_pdf_pro(request):
    """Export PRO test results to PDF with Latvian character support"""
    try:
        result = request.session.get('pro_result')
        if not result:
            return HttpResponse("Nav rezultātu. Lūdzu, vispirms nokārtojiet testu.", status=400)

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm)
        story = []
        styles = getSampleStyleSheet()

        # Create custom styles with Unicode font
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontName='DejaVuSans-Bold',
            fontSize=24,
            textColor=colors.HexColor('#1a335d'),
            spaceAfter=30,
            alignment=TA_CENTER
        )
        
        subtitle_style = ParagraphStyle(
            'CustomSubtitle',
            parent=styles['Normal'],
            fontName='DejaVuSans-Bold',
            fontSize=12,
            textColor=colors.HexColor('#f59e0b'),
            alignment=TA_CENTER,
            spaceAfter=20
        )
        
        normal_style = ParagraphStyle(
            'CustomNormal',
            parent=styles['Normal'],
            fontName='DejaVuSans',
            fontSize=11,
            leading=16
        )
        
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontName='DejaVuSans-Bold',
            fontSize=14,
            textColor=colors.HexColor('#1a335d'),
            spaceAfter=10,
            spaceBefore=20
        )

        # Title
        story.append(Paragraph("Finanšu Pratības Novērtējums", title_style))
        story.append(Paragraph("PRO ANALĪZE", subtitle_style))
        story.append(Spacer(1, 20))

        # Score
        score_data = [
            ['Jūsu rezultāts:', f"{result['raw_score']}/65 punkti"],
            ['Procenti:', f"{result['score']}%"],
            ['Līmenis:', result['level_text']]
        ]
        score_table = Table(score_data, colWidths=[8 * cm, 8 * cm])
        score_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8f9fa')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#1a335d')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'DejaVuSans-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey)
        ]))
        story.append(score_table)
        story.append(Spacer(1, 20))

        # AI Recommendations
        story.append(Paragraph("AI Personalizēti Ieteikumi", heading_style))
        story.append(Spacer(1, 10))

        for i, tip in enumerate(result['tips'], 1):
            story.append(Paragraph(f"{i}. {tip}", normal_style))
            story.append(Spacer(1, 10))

        # Footer
        story.append(Spacer(1, 30))
        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontName='DejaVuSans',
            fontSize=9,
            textColor=colors.HexColor('#94a3b8'),
            alignment=TA_CENTER
        )
        story.append(Paragraph("Finanšu Pratība © 2025 | PRO Analīze ar AI ieteikumiem", footer_style))
        
        disclaimer_style = ParagraphStyle(
            'Disclaimer',
            parent=styles['Normal'],
            fontName='DejaVuSans',
            fontSize=8,
            textColor=colors.HexColor('#94a3b8'),
            alignment=TA_CENTER
        )
        story.append(Spacer(1, 10))
        story.append(Paragraph("⚠️ Šī informācija ir tikai izglītojošiem nolūkiem un neaizstāj profesionālu finanšu konsultāciju.", disclaimer_style))

        doc.build(story)
        buffer.seek(0)

        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="finansu_pratiba_pro.pdf"'
        return response

    except Exception as e:
        logger.error(f"PDF export error (pro): {e}")
        return HttpResponse(f"Kļūda PDF izveidē: {str(e)}", status=500)


# ============= STRIPE PAYMENT FUNCTIONS =============

@csrf_exempt
def create_checkout_session(request):
    """Create Stripe checkout session"""
    if request.method == 'POST':
        try:
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'eur',
                        'unit_amount': 249,  # €2.49 in cents
                        'product_data': {
                            'name': 'Finanšu Pratības Pro Analīze',
                            'description': '15 jautājumu detalizēts tests ar AI ieteikumiem',
                        },
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url='https://finbriv.vercel.app/payment/success/',
                cancel_url='https://finbriv.vercel.app/payment/cancel/',
            )

            return JsonResponse({'sessionId': checkout_session.id})

        except Exception as e:
            logger.error(f"Stripe session creation error: {e}")
            return JsonResponse({'error': str(e)}, status=400)

    return JsonResponse({'error': 'Invalid request method'}, status=405)


def payment_success(request):
    """Payment success page"""
    return render(request, 'payment_success.html')


def payment_cancel(request):
    """Payment cancelled page"""
    return render(request, 'payment_cancel.html')


def documentation(request):
    """Documentation page with test methodology and references"""
    return render(request, 'documentation.html')


def privacy(request):
    """Privacy policy page"""
    return render(request, 'privacy.html')


def download_pdf(request, filename):
    """Allow users to download PDF files from the pdfs folder"""
    import urllib.parse
    from django.http import FileResponse, Http404
    
    # Path to the pdfs folder (one level up from project root)
    pdfs_dir = os.path.join(settings.BASE_DIR.parent, 'pdfs')
    
    # Decode URL-encoded filename
    filename = urllib.parse.unquote(filename)
    
    file_path = os.path.join(pdfs_dir, filename)
    
    # Security: prevent directory traversal attacks
    file_path = os.path.normpath(file_path)
    if not file_path.startswith(os.path.normpath(pdfs_dir)):
        raise Http404("PDF file not found")
    
    # Check if file exists
    if not os.path.exists(file_path):
        logger.error(f"PDF file not found: {file_path}")
        raise Http404(f"PDF file not found: {filename}")
    
    # Open and return the file
    try:
        response = FileResponse(open(file_path, 'rb'), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{urllib.parse.quote(filename)}"'
        return response
    except Exception as e:
        logger.error(f"PDF download error: {e}")
        raise Http404("Error downloading PDF")


@csrf_exempt
def stripe_webhook(request):
    """Handle Stripe webhooks"""
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        return HttpResponse(status=400)

    # Handle the event
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        # You can add logic here to grant access to PRO features
        logger.info(f"Payment successful: {session['id']}")

    return HttpResponse(status=200)
